Kalmon
======

## About

This is a command-line utility for controlling things (generally ESP8266 +
nodemcu) running [kalmon](https://github.com/kalmanolah/kalmon-ESP8266).

## Installation

```
$ sudo pip3 install -U git+https://github.com/kalmanolah/py-kalmon.git
```

## Dependencies

* python3
* click
* paho-mqtt
* prettytable
* gitpython

## TODO

* Progress bars when not using "plain" output
* Coloured success/error state when not using "plain" output
* Executing against multiple nodes using masks (eg: "ESP-1515*")
* Module toggle, add, remove, list commands
* Add module index
* Start versioning

## License

See [LICENSE](LICENSE).
