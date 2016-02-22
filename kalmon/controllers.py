"""Controllers."""


class Controller:

    """Base kalmon controller."""

    def handle_command(self, command):
        """Handle a command."""
        raise NotImplementedError()


class GPIOController(Controller):

    """Kalmon GPIO controller."""

    topic_template = '/nodes/%(node)s/commands/gpio/control'

    def handle_command(self, node, command):
        """Handle a command."""
        method, pin, state = command.split(',')
        pin = int(pin)
        state = state == 'HIGH'

        topic = self.topic_template % locals()
        payload = {
            'state': state,
            'pin': pin,
            'type': method,
        }

        return {
            'mqtt_messages': [(topic, payload)]
        }


class WS2812Controller(Controller):

    """Kalmon WS2812 LED strip/ring thingy controller."""

    topic_template = '/nodes/%(node)s/commands/ws2812/control'

    def handle_command(self, node, command):
        """Handle a command."""
        hue = saturation = intensity = 0
        effect = 'fade'

        if command == 'OFF':
            intensity = 0
        elif command == 'ON':
            intensity = 0.75
        else:
            hue, saturation, intensity = command.split(',')
            saturation = float(saturation) / 100
            intensity = float(intensity) / 100

        topic = self.topic_template % locals()

        payload = {
            'hsi': [hue, saturation, intensity],
            'type': effect
        }

        return {
            'mqtt_messages': [(topic, payload)]
        }
