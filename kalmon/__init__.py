"""Main module."""
import click
import logging
import paho.mqtt.publish as mqtt_publish
from pkg_resources import iter_entry_points


logger = logging.getLogger(__name__)


@click.command()
@click.option('--debug', '-d', is_flag=True)
@click.argument('node')
@click.argument('type')
@click.argument('command')
def main(debug, node, type, command):
    """Handle a kalmon command."""
    mqtt_messages = []

    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)
    logger.debug('Initializing')
    logger.debug('Processing command "%s" of type "%s" for node "%s"', command, type, node)

    entry_point_name = type
    entry_point_group = 'kalmon.controllers'
    logger.debug('Looking for entry points in group "%s" with name "%s"', entry_point_group, entry_point_name)

    for entry_point in iter_entry_points(group=entry_point_group, name=entry_point_name):
        logger.debug('Instantiating controller "%s"', entry_point.name)
        ctrl_class = entry_point.load()
        ctrl_instance = ctrl_class()

        logger.debug('Passing command to controller "%s"', entry_point.name)
        result = ctrl_instance.handle_command(node, command)
        logger.debug('Controller command handling successful')

        if result and result.get('mqtt_messages', None):
            logger.debug('Adding %s message(s) to MQTT queue', len(result['mqtt_messages']))
            mqtt_messages += result['mqtt_messages']

    if mqtt_messages:
        logger.debug('Sending %s message(s) over MQTT', len(result['mqtt_messages']))
        mqtt_messages = [{'topic': x[0], 'payload': x[1]} for x in mqtt_messages]
        for mqtt_message in mqtt_messages:
            logger.debug('MQTT: "%s" << "%s"', mqtt_message['topic'], mqtt_message['payload'])

        mqtt_publish.multiple(
            mqtt_messages,
            hostname=mqtt_host,
            port=mqtt_port,
            auth={
                'username': mqtt_username,
                'password': mqtt_password
            }
        )

    logger.debug('Finished')

if __name__ == '__main__':
    main(obj={})
