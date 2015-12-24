"""Controllers."""


class Controller:

    """Base kalmon controller."""

    def handle_command(self, command):
        """Handle a command."""
        raise NotImplementedError()


class GPIOController(Controller):

    """Kalmon GPIO controller."""

    topic_template = '/nodes/%(node)s/commands/gpio/control'
    payload_template = '{"state":%(state)s,"pin":%(pin)s,"type":"%(method)s"}'

    def handle_command(self, node, command):
        """Handle a command."""
        payload = self.payload_template
        method, pin, state = command.split(',')
        pin = int(pin)
        state = 'true' if state == 'HIGH' else 'false'

        topic = self.topic_template % locals()
        payload = payload % locals()

        return {
            'mqtt_messages': [(topic, payload)]
        }


class WS2812Controller(Controller):

    """Kalmon WS2812 LED strip/ring thingy controller."""

    topic_template = '/nodes/%(node)s/commands/ws2812/control'
    payload_template = '{"hsi":[%(hue)s,%(saturation)s,%(intensity)s],"type":"%(effect)s"}'

    def handle_command(self, node, command):
        """Handle a command."""
        payload = self.payload_template
        hue = saturation = intensity = 0
        effect = 'fade'

        if command == 'OFF':
            intensity = 0
            payload = '{"intensity":%(intensity)s,"type":"%(effect)s"}'
        elif command == 'ON':
            intensity = 0.75
            payload = '{"intensity":%(intensity)s,"type":"%(effect)s"}'
        else:
            hue, saturation, intensity = command.split(',')
            saturation = float(saturation) / 100
            intensity = float(intensity) / 100

        topic = self.topic_template % locals()
        payload = payload % locals()

        return {
            'mqtt_messages': [(topic, payload)]
        }
