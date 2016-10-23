"""Main module."""
import click
import logging
import paho.mqtt.client as mqtt
from pkg_resources import iter_entry_points
from threading import Timer, Event
from prettytable import PrettyTable, PLAIN_COLUMNS, DEFAULT
from math import ceil
import re
import git
import time
import json
import os
import ssl
import socket
import select
import netifaces
import shortuuid


FW_URL = 'https://github.com/kalmanolah/kalmon-ESP8266.git'
FW_SRC_PREFIX = 'src/'
FW_MODULE_PREFIX = 'module/'
FW_BUILTIN_MODULES = ['kalmon']
CFG_KEY_VERSION = 'kalmon_ref'


logger = logging.getLogger(__name__)


class KalmonController:

    """Kalmon Controller."""

    defaults = {}
    nodes = {}

    def __init__(self, options={}, debug=False, timeout=2500):
        """Constructor."""
        logger.debug('Initializing controller of type "%s"', self.__class__.__name__)

        self.options = self.defaults.copy()
        self.options.update(options)

        self.debug = debug
        self.timeout = timeout

        self.start()

    def __enter__(self):
        """Enter resource scope."""
        logger.debug('Entering controller scope')
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Exit resource scope."""
        logger.debug('Exiting controller scope')
        self.close()

    def close(self):
        """Perform closing tasks and clean up."""
        logger.debug('Closing controller')
        self.stop()

    def start(self):
        """Initialize and start the controller."""
        logger.debug('Starting controller')
        pass

    def stop(self):
        """Stop the controller."""
        logger.debug('Stopping controller')
        pass

    def select_node(self, node_id):
        """Select a node by ID."""
        logger.debug('Selecting node with ID "%s"', node_id)

        if node_id not in self.nodes:
            node = KalmonNode(self, node_id)
            self.nodes[node_id] = node

        return self.nodes[node_id]

    def get_node_list(self):
        """Get a list of available node IDs."""
        return []

    def wait(self):
        """Wait for a bit."""
        time.sleep(0.010)

    def publish(self, node, topic, data={}, on_publish=None, on_response=None):
        """Publish a message for a node."""
        pass

    def publish_and_wait(self, node, topic, data={}):
        """Publish a message for a node, waiting for a response and returning the result."""
        pass


class KalmonTCPController(KalmonController):

    """Kalmon TCP Controller."""

    defaults = {
        'port': 80,
    }

    def get_node_list(self):
        """Get a list of available node IDs."""
        logger.debug('Retrieving node list')
        self.node_ids = []

        # Iterate over interfaces, try to grab gateway ipv4 addr
        # Try to /ping gateway over TCP using default port.. if we get a pong, we may get a node ID
        gateways = netifaces.gateways()
        gateways = gateways.get(netifaces.AF_INET, [])

        for gateway in gateways:
            node_id = gateway[0]
            node = self.select_node(node_id)
            info = node.get_info()

            if info and info.get('node'):
                logger.debug('Found node with ID "%s"', node_id)
                self.node_ids.append(node_id)

        return self.node_ids

    def publish(self, node, topic, data={}, on_publish=None, on_response=None):
        """Publish a message for a node."""
        logger.debug('Publishing "%s" data to node "%s"', topic, node.node_id)

        logger.debug('Connecting to "%s:%s" over TCP socket', node.node_id, self.options['port'])
        conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        conn.connect((node.node_id, self.options['port']))

        # JSON encode dicts, lists and stuff
        if type(data) in [dict, list, tuple]:
            data = json.dumps(data)

        payload = {
            'cmd': topic,
            'data': data,
        }
        payload = json.dumps(payload)
        payload = bytes(payload, 'utf8')

        logger.debug('Sending %s bytes of data', len(payload))
        conn.send(payload)

        if on_publish:
            logger.debug('Calling publish callback')
            on_publish()

        conn.setblocking(0)
        ready = select.select([conn], [], [], self.timeout / 1000)
        payload, data = None, None

        if ready[0]:
            payload = conn.recv(8192)
            payload = str(payload, 'utf8')
            logger.debug('Received %s bytes of data' % len(payload))

            try:
                data = json.loads(payload)
            except json.decoder.JSONDecodeError as e:
                logger.error('Error while JSON decoding message payload: %s' % e)

            if on_response:
                logger.debug('Calling response callback')
                on_response(payload, data)

        logger.debug('Closing connection')
        conn.close()

        return payload, data

    def publish_and_wait(self, node, topic, data={}):
        """Publish a message for a node, waiting for a response and returning the result."""
        return self.publish(node, topic, data=data)


class KalmonMQTTController(KalmonController):

    """Kalmon MQTT Controller."""

    defaults = {
        'host': 'localhost',
        'port': 1883,
        'keepalive': 60,
        'username': None,
        'password': None,
        'secure': False,
    }

    publish_callbacks = {}
    response_callbacks = {}
    subscriptions = []
    publishes = []
    connected = False

    def __init__(self, *args, **kwargs):
        """Constructor."""
        super().__init__(*args, **kwargs)

    def start(self):
        """Start the controller."""
        super().start()
        self.start_mqtt()

    def stop(self):
        """Stop the controller."""
        self.stop_mqtt()
        super().stop()

    def publish(self, node, topic, **kwargs):
        """Publish a message for a node."""
        topic = self.generate_node_topic(node, topic)

        return self.publish_mqtt(topic, **kwargs)

    def publish_and_wait(self, node, topic, **kwargs):
        """Publish a message for a node, waiting for a response and returning the result."""
        topic = self.generate_node_topic(node, topic)

        return self.publish_and_wait_mqtt(topic, **kwargs)

    def select_node(self, *args):
        """Select a node by ID."""
        node = super().select_node(*args)
        self.subscribe_mqtt(self.generate_node_topic(node, '#', type='responses'))

        return node

    def get_node_list(self):
        """Get a list of available node IDs."""
        logger.debug('Updating node list')
        self.subscribe_mqtt('/nodes/+/responses/ping')
        self.node_ids = []

        def on_response(payload, data):
            if data and data.get('node', None):
                node_id = data['node']
                logger.debug('Found node with ID "%s"' % node_id)

                if node_id not in self.node_ids:
                    self.node_ids.append(node_id)

            return False

        self.publish_mqtt('/ping', on_response=on_response)
        time.sleep(self.timeout / 1000)

        return self.node_ids

    def start_mqtt(self):
        """Initialize and start the MQTT client."""
        def on_connect(client, userdata, flags, rc):
            logger.debug('MQTT client connected with result code "%s"' % rc)
            self.connected = True

            for topic in self.subscriptions:
                logger.debug('Subscribing to MQTT topic "%s"' % topic)
                client.subscribe(topic)

        def on_disconnect(client, userdata, rc):
            logger.debug('MQTT client disconnected with result code "%s"' % rc)
            self.connected = False

        def on_message(client, userdata, message):
            payload = str(message.payload, 'utf8')
            logger.debug('Received %s byte MQTT message at topic "%s"' % (len(payload), message.topic))

            data = None

            if payload:
                try:
                    data = json.loads(payload)
                except json.decoder.JSONDecodeError as e:
                    logger.error('Error while JSON decoding message payload: %s' % e)

            if data and data.get('rid', None):
                rid = data['rid']

                if rid in self.response_callbacks:
                    result = self.response_callbacks[rid](payload, data)

                    if result is not False:
                        self.response_callbacks.pop(rid, None)

        def on_publish(client, userdata, mid):
            logger.debug('Published message "%s" over MQTT' % mid)

            # Since the message ID is only generated when publishing,
            # we have to publish BEFORE registering any callbacks.
            # To prevent issues, we wait until these callbacks have been
            # registered before continueing
            while mid not in self.publishes:
                self.wait()

            self.publishes.remove(mid)

            if mid in self.publish_callbacks:
                self.publish_callbacks[mid]()
                self.publish_callbacks.pop(mid, None)

        self.mqtt = mqtt.Client()
        self.mqtt.on_connect = on_connect
        self.mqtt.on_disconnect = on_disconnect
        self.mqtt.on_message = on_message
        self.mqtt.on_publish = on_publish

        if self.options.get('secure', False):
            logger.debug('Enabling TLS')
            self.mqtt.tls_set('/etc/ssl/certs/ca-certificates.crt', cert_reqs=ssl.CERT_NONE)
            self.mqtt.tls_insecure_set(True)

        if self.options.get('username', None):
            logger.debug('Using username "%s" for MQTT %s a password',
                         self.options['username'], 'WITH' if self.options.get('password', None) else 'WITHOUT')
            self.mqtt.username_pw_set(self.options['username'], password=self.options.get('password', None))

        try:
            logger.debug('Connecting to MQTT server at "%s:%s"' % (self.options['host'], self.options['port']))
            self.mqtt.connect(self.options['host'], self.options['port'], self.options['keepalive'])
            self.mqtt.loop_start()
        except Exception as e:
            logger.error('Error while connecting to MQTT server: %s' % e)
            exit(1)

        while not self.connected:
            self.wait()

    def stop_mqtt(self):
        """Stop and disconnect all MQTT-related activity."""
        if self.mqtt:
            logger.debug('Disconnecting from MQTT server')
            self.mqtt.disconnect()
            self.mqtt.loop_stop()

    def publish_mqtt(self, topic, data={}, on_publish=None, on_response=None, inject_rid=True):
        """Publish a message to the MQTT broker."""
        payload = data

        # If this is a dict and we're allowed to inject a request ID, do so
        # Injecting a request ID allows the nodes to respond and us to execute callbacks
        if (type(data) is dict) and inject_rid:
            data['rid'] = str(shortuuid.uuid())

        # JSON encode dicts, lists and stuff
        if type(data) in [dict, list, tuple]:
            payload = json.dumps(data)

        result, mid = self.mqtt.publish(topic, payload, qos=1)

        if on_publish:
            self.publish_callbacks[mid] = on_publish

        if on_response and data and data.get('rid', None):
            self.response_callbacks[data['rid']] = on_response

        self.publishes.append(mid)

        while mid in self.publishes:
            self.wait()

    def publish_and_wait_mqtt(self, topic, data={}):
        """Publish a message to the MQTT broker, waiting for a response and returning the result."""
        result = [None, None]
        finish = Event()

        def on_response(payload, data):
            result[0] = payload
            result[1] = data

        def do_timeout():
            finish.set()

        self.publish_mqtt(topic, data, on_response=on_response)
        timer = Timer(self.timeout / 1000, do_timeout)
        timer.start()

        while (not result[0]) and (not finish.is_set()):
            self.wait()

        timer.cancel()

        if finish.is_set():
            raise TimeoutError('Reached timeout of %sms while waiting for response!' % self.timeout)

        return result

    def subscribe_mqtt(self, topic):
        """Subscribe to a specific MQTT topic."""
        if topic not in self.subscriptions:
            self.subscriptions.append(topic)
            self.mqtt.subscribe(topic)

    def generate_node_topic(self, node, topic, type='commands'):
        """Generate a full topic from a partial topic for a node."""
        return '/nodes/%s/%s/%s' % (node.node_id, type, topic)


class KalmonNode:

    """Kalmon Node."""

    def __init__(self, controller, node_id):
        """Constructor."""
        logger.debug('Spawning Kalmon node with ID "%s"' % node_id)

        self.node_id = node_id
        self.controller = controller

    def attempt_restart(self):
        """Attempt to restart the node."""
        self.controller.publish(self, 'restart')

    def get_info(self):
        """Get node info."""
        payload, data = self.controller.publish_and_wait(self, 'info')

        return data

    def get_files(self):
        """Get node files."""
        info = self.get_info()
        data = info.get('files', []) if info else []

        return data

    def get_stats(self):
        """Get node stats."""
        info = self.get_info()
        data = info.get('stats', {}) if info else {}
        # data['node'] = data['node'] if data.get('node') else info['node']

        return data

    def create_file(self, filename, content='', compile=False):
        """Create a file."""
        logger.debug('Creating file "%s" on node "%s" containing %s bytes' % (filename, self.node_id, len(content)))

        chunk_size = 256
        content_size = len(content)
        chunks = ceil(content_size / (chunk_size * 1.0))

        logger.debug('Splitting file into %s chunks due to size' % chunks)

        for i in range(0, chunks):
            chunk_offset = i * chunk_size
            chunk_content = content[chunk_offset:chunk_offset + chunk_size]

            payload, data = self.controller.publish_and_wait(self, 'files/create', data={
                'file': filename,
                'content': chunk_content,
                'offset': chunk_offset,
                'compile': compile and (i == (chunks - 1)),
            })

        return

    def remove_file(self, filename):
        """Remove a file."""
        logger.debug('Removing file "%s" from node "%s"' % (filename, self.node_id))

        payload, data = self.controller.publish_and_wait(self, 'files/remove', data={
            'file': filename,
        })

        return data

    def get_configuration(self):
        """Get node configuration."""
        info = self.get_info()
        data = info.get('cfg', {}) if info else {}

        return data

    def set_configuration(self, key, value=None):
        """Set node configuration."""
        logger.debug('Setting configuration key "%s" of node "%s" to value "%s"' % (self.node_id, key, value))

        payload, data = self.controller.publish_and_wait(self, 'cfg/set', data={
            'key': key,
            'value': value,
        })

        return data


@click.group()
@click.option('--debug', '-d', is_flag=True)
@click.option('--plain', '-p', is_flag=True, help='Use plain output, for easier scripting.')
@click.option('--mqtthost', '-mqh', default='localhost')
@click.option('--mqttport', '-mqp', default=1883)
@click.option('--mqttusername', '-mqu', default=None)
@click.option('--mqttpassword', '-mqP', default=None)
@click.option('--mqttsecure', '-mqS', default=False)
@click.option('--tcpport', '-tP', default=80)
@click.option('--controller', '-c', default='MQTT', type=click.Choice(['MQTT', 'TCP']), help='Controller to use.')
@click.option('--timeout', '-t', default=2500, help='Timeout for RPC operations in milliseconds.')
@click.pass_context
def kalmon(ctx, debug, plain, mqtthost, mqttport, mqttusername, mqttpassword, mqttsecure, tcpport, controller, timeout):
    """Control devices running Kalmon."""
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)

    ctx.obj['debug'] = debug
    ctx.obj['plain'] = plain
    ctx.obj['timeout'] = timeout

    if controller == 'MQTT':
        options = {
            'host': mqtthost,
            'port': mqttport,
            'username': mqttusername,
            'password': mqttpassword,
            'secure': mqttsecure,
        }
        controller = KalmonMQTTController(options=options, debug=debug, timeout=timeout)
    elif controller == 'TCP':
        options = {
            'port': tcpport,
        }
        controller = KalmonTCPController(options=options, debug=debug, timeout=timeout)

    ctx.obj['controller'] = controller


@kalmon.command('list')
@click.pass_context
def node_list(ctx):
    """Get a list of available nodes."""
    nodes = ctx.obj['controller'].get_node_list()
    nodes = [[x] for x in nodes]
    click.echo(generate_table(['NODE'], nodes, sort='NODE', plain=ctx.obj['plain']))


@kalmon.group('node')
@click.argument('node-id')
@click.pass_context
def node_select(ctx, node_id):
    """Select a node."""
    node = ctx.obj['controller'].select_node(node_id)
    ctx.obj['node'] = node


@node_select.command('restart')
@click.pass_context
def node_restart(ctx):
    """Attempt to restart a node."""
    ctx.obj['node'].attempt_restart()


@node_select.command('stats')
@click.pass_context
def node_stats(ctx):
    """Get stats for a node."""
    try:
        data = ctx.obj['node'].get_stats()
    except TimeoutError as e:
        logger.error('Error: %s' % e)
        exit(1)

    data = [[k, v] for k, v in data.items()]
    click.echo(generate_table(['KEY', 'VALUE'], data, sort='KEY', plain=ctx.obj['plain']))


@node_select.group('file')
@click.pass_context
def node_file(ctx):
    """Node file operations."""
    pass


@node_file.command('list')
@click.pass_context
def node_file_list(ctx):
    """Get node files."""
    try:
        data = ctx.obj['node'].get_files()
    except TimeoutError as e:
        logger.error('Error: %s' % e)
        exit(1)

    click.echo(generate_table(['FILE', 'SIZE'], data, sort='FILE', plain=ctx.obj['plain']))


@node_file.command('upload')
@click.argument('file', type=click.Path(exists=True))
@click.option('--filename', '-f', help='Set a custom name for the file.')
@click.pass_context
def node_file_upload(ctx, file, filename):
    """Upload a file to a node."""
    filepath = click.format_filename(file)
    filename = filename if filename else filepath

    with open(file, "r") as f:
        content = f.read()

    try:
        ctx.obj['node'].create_file(filename, content=content)
    except TimeoutError as e:
        logger.error('Error: %s' % e)
        exit(1)


@node_file.command('create')
@click.argument('filename')
@click.argument('content', default='\n', required=False)
@click.option('--from-stdin', '-in', help='Supply file content by piping to STDIN.', is_flag=True)
@click.pass_context
def node_file_create(ctx, filename, content, from_stdin):
    """Create a file on a node."""
    if from_stdin:
        content = click.get_text_stream('stdin').read(8196)

    try:
        ctx.obj['node'].create_file(filename, content=content)
    except TimeoutError as e:
        logger.error('Error: %s' % e)
        exit(1)


@node_file.command('remove')
@click.argument('filename')
@click.pass_context
def node_file_remove(ctx, filename):
    """Remove a file from a node."""
    try:
        ctx.obj['node'].remove_file(filename)
    except TimeoutError as e:
        logger.error('Error: %s' % e)
        exit(1)


@node_select.group('cfg')
@click.pass_context
def node_configuration(ctx):
    """Node configuration operations."""
    pass


@node_configuration.command('list')
@click.pass_context
def node_configuration_list(ctx):
    """Get node configuration."""
    try:
        data = ctx.obj['node'].get_configuration()
    except TimeoutError as e:
        logger.error('Error: %s' % e)
        exit(1)

    data = [[k, v] for k, v in data.items()]
    click.echo(generate_table(['KEY', 'VALUE'], data, sort='KEY', plain=ctx.obj['plain']))


@node_configuration.command('set')
@click.argument('key')
@click.argument('value')
@click.pass_context
def node_configuration_set(ctx, key, value):
    """Set node configuration."""
    if value.lower() in ['true']:
        value = True
    elif value.lower() in ['false']:
        value = False
    elif value.lower() in ['null', 'none', 'nil']:
        value = None
    elif value.isdigit():
        value = int(value)
    else:
        try:
            value = float(value)
        except ValueError:
            pass

    try:
        ctx.obj['node'].set_configuration(key, value=value)
    except TimeoutError as e:
        logger.error('Error: %s' % e)
        exit(1)


@node_select.command('upgrade')
@click.option('--repository-url', '-u', default=FW_URL, help='Git url for the repository.')
@click.option('--clone-path', '-p', default='~/.kalmon/src', help='Path to clone repository to.')
@click.option('--module', '-m', multiple=True, help='Module to enable and upgrade.')
@click.option('--reference-only', '-r', is_flag=True, help='Only update the version reference without touching files.')
@click.pass_context
def node_upgrade(ctx, repository_url, clone_path, reference_only, module):
    """Upgrade a node."""
    def is_source_file(f):
        return f.startswith(FW_SRC_PREFIX)

    def is_module_file(f):
        return f.startswith(os.path.join(FW_SRC_PREFIX, FW_MODULE_PREFIX))

    def get_module_name(f):
        match = re.match(os.path.join(FW_SRC_PREFIX, FW_MODULE_PREFIX, '([a-zA-Z0-9_-]+)\.(lua|lc)'), f)

        return match.group(1) if match else None

    def get_module_path(f):
        return os.path.join(FW_SRC_PREFIX, FW_MODULE_PREFIX, '%s.lua' % f)

    def get_node_path(f):
        return f[len(FW_SRC_PREFIX):] if f.startswith(FW_SRC_PREFIX) else f

    node = ctx.obj['node']
    logger.debug('Upgrading node "%s"' % node.node_id)

    clone_path = os.path.expanduser(clone_path)
    os.makedirs(clone_path, exist_ok=True)

    try:
        repo = git.repo.base.Repo(clone_path)
    except (git.exc.InvalidGitRepositoryError, git.exc.NoSuchPathError):
        logger.warn('Repository does not exist yet, cloning it now')
        repo = git.repo.base.Repo.clone_from(repository_url, clone_path)

    logger.debug('Performing a pull of the repository')
    repo.remotes.origin.pull()

    version_ref_length = 7
    latest_version_ref = str(repo.head.commit)[:version_ref_length]

    if not reference_only:
        logger.debug('Getting version and enabled modules from node')
        cfg = node.get_configuration()
        files = node.get_files()

        enabled_modules = {}

        for f in files:
            filename = os.path.join(FW_SRC_PREFIX, f[0])

            if is_module_file(filename):
                enabled_modules[get_module_name(filename)] = filename

        required_modules = list(module) if module else list(enabled_modules.keys()).copy()
        required_modules += FW_BUILTIN_MODULES.copy()

        remove_files = []
        upload_files = []

        current_version_ref = cfg.get(CFG_KEY_VERSION, None)

        if current_version_ref:
            logger.debug('Found commit hash "%s" on node' % current_version_ref)
        else:
            for commit in repo.iter_commits(rev='HEAD', max_parents=0):
                current_version_ref = str(commit)[:version_ref_length]

            logger.debug('Using first commit\'s hash "%s", since none could be found on node' % current_version_ref)

        logger.debug('Performing diff between HEAD and commit "%s" to determine file changes' % current_version_ref)
        diff = repo.commit(current_version_ref).diff(latest_version_ref)

        for d in diff.iter_change_type('A'):
            upload_files.append(d.b_path)

        for d in diff.iter_change_type('D'):
            remove_files.append(d.a_path)

        for d in diff.iter_change_type('M'):
            upload_files.append(d.b_path)

        for d in diff.iter_change_type('R'):
            remove_files.append(d.a_path)
            upload_files.append(d.b_path)

        def is_valid_file(f):
            return is_source_file(f) and ((not is_module_file(f)) or (get_module_name(f) in required_modules))

        upload_files = [x for x in upload_files if is_valid_file(x)]
        remove_files = [x for x in remove_files if is_valid_file(x)]

        # Files which have to be both uploaded and removed should not be removed
        remove_files = [x for x in remove_files if x not in upload_files]

        for module in required_modules:
            f = get_module_path(module)

            if (module not in enabled_modules.keys()) and (f not in upload_files) and (f not in remove_files):
                logger.debug('Uploading module "%s" in addition to other changes' % module)
                upload_files.append(f)

        for module, f in enabled_modules.items():
            if (module not in required_modules) and (f not in remove_files):
                logger.debug('Removing module "%s" in addition to other changes' % module)
                module_files = [f, get_module_path(module)]

                for module_file in module_files:
                    remove_files.append(module_file)

                    if module_file in upload_files:
                        upload_files.remove(module_file)

        logger.debug('Determined that %s files are to be removed, %s files are to be uploaded' %
                     (len(remove_files), len(upload_files)))

        for f in remove_files:
            node.remove_file(get_node_path(f))

        for f in upload_files:
            filename = get_node_path(f)
            filepath = os.path.join(clone_path, f)
            content = ''

            with open(filepath, "r") as f:
                content = f.read()

            # If the filename ends with .lua, consider it a source file and attempt compilation
            # compile = filename.endswith('.lua') and (filename != os.path.join(FW_SRC_PREFIX, 'init.lua'))
            compile = False
            node.create_file(filename, content=content, compile=compile)

    logger.debug('Upgrade finished, writing commit hash "%s" to node' % latest_version_ref)
    node.set_configuration(CFG_KEY_VERSION, latest_version_ref)

    logger.debug('Restarting node')
    node.attempt_restart()


@node_select.command('ctrl')
@click.argument('type')
@click.argument('command')
@click.pass_context
def node_custom_control(ctx, type, command):
    """Attempt to execute a custom controller against a node."""
    node = ctx.obj['node']
    mqtt_messages = []

    logger.debug('Processing command "%s" of type "%s" for node "%s"', command, type, node.node_id)

    entry_point_name = type
    entry_point_group = 'kalmon.controllers'
    logger.debug('Looking for entry points in group "%s" with name "%s"', entry_point_group, entry_point_name)

    for entry_point in iter_entry_points(group=entry_point_group, name=entry_point_name):
        logger.debug('Instantiating controller "%s"', entry_point.name)
        ctrl_class = entry_point.load()
        ctrl_instance = ctrl_class()

        logger.debug('Passing command to controller "%s"', entry_point.name)
        result = ctrl_instance.handle_command(node.node_id, command)
        logger.debug('Controller command handling successful')

        if result and result.get('mqtt_messages', None):
            logger.debug('Adding %s message(s) to MQTT queue', len(result['mqtt_messages']))
            mqtt_messages += result['mqtt_messages']

    if mqtt_messages:
        logger.debug('Sending %s message(s) over MQTT', len(result['mqtt_messages']))
        mqtt_messages = [{'topic': x[0], 'payload': x[1]} for x in mqtt_messages]
        for mqtt_message in mqtt_messages:
            logger.debug('MQTT: "%s" << "%s"', mqtt_message['topic'], mqtt_message['payload'])
            ctx.obj['controller'].publish_mqtt(mqtt_message['topic'], data=mqtt_message['payload'])

    logger.debug('Finished')


def generate_table(columns, rows, plain=False, sort=None, reversesort=False):
    """Generate a pretty table."""
    tbl = PrettyTable(columns)
    tbl.set_style(PLAIN_COLUMNS if plain else DEFAULT)
    tbl.header = not plain
    [tbl.add_row(x) for x in rows]
    tbl.align = 'l'

    if sort:
        tbl.sortby = sort

    tbl.reversesort = reversesort

    return tbl


def cli():
    """Command-line entry point."""
    kalmon(obj={}, auto_envvar_prefix='KALMON')


if __name__ == '__main__':
    cli()
