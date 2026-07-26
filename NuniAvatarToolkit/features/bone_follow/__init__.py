from . import properties, operators, panel

_modules = (properties, operators, panel)


def register():
  for module in _modules:
    module.register()


def unregister():
  for module in reversed(_modules):
    module.unregister()
