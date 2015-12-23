"""Controllers."""


class Controller:

    """Base kalmon controller."""

    def handle_command(self, command):
        """Handle a command."""
        raise NotImplementedError()


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
