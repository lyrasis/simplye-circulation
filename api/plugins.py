import logging
import pkg_resources
import importlib

def get_installed_plugins():
    plugins = []
    packages = pkg_resources.working_set
    for package in packages:
        if package.key.startswith("cm-plugin"):
            try:
                module = importlib.import_module(package.key.replace('-', "_"))
            except Exception as er:
                logging.error("Unable to import plugin module %s. Er: ", package.key, er)
                continue
            
            valid = True
            for attr in Plugin.required_attributes():
                if not hasattr(module, attr):
                    valid = False
                    logging.error("Plugin module %s incomplete, not initialized. Missing attr %s",
                        package.key, attr)

            if valid:
                plugins.append(Plugin(package.key, module.routes, module.run_func))

    return plugins


class Plugin(object):
    """ A class repreting to represent plugins """
    def __init__(self, name, routes, functions):
        self.name = name
        self.routes = routes
        self.functions = functions

    @classmethod
    def required_attributes(cls):
        return ["routes", "run_func"]

    def enable_route(self, app):
        for route in self.routes:
            logging.info("Enabling plugin %s", self.name)
            defaults = {"app": app}
            try:
                app.add_url_rule(defaults=defaults, **route)
            except Exception as er:
                logging.error("Plugin %s: Unable to activate. Er: ", self.name, er)
                continue

            logging.info("Plugin %s: activate", self.name)

    def run_functions(self):
        for function in self.functions:
            function["func"]().run()

