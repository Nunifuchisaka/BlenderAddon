from . import api, properties, operators, panel

run = api.run

_modules = (properties, operators, panel)


def register():
    for module in _modules:
        module.register()


def unregister():
    for module in reversed(_modules):
        module.unregister()
