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
                plugins.append(Plugin(package.key, module.routes, module.scripts))

    return plugins


class Plugin(object):
    """ A class repreting to represent plugins """
    PLUGIN_PATH = "/plugin"

    def __init__(self, name, routes, scripts):
        self.name = name
        self.routes = routes
        self.scripts = scripts

    @classmethod
    def required_attributes(cls):
        return ["routes", "scripts"]

    def enable_route(self, app):
        for route in self.routes:
            logging.info("Enabling plugin %s", self.name)
            defaults = {"app": app}
            try:
                if route["rule"].startswith("/"):
                    route["rule"] = self.PLUGIN_PATH + route["rule"]
                else:
                    route["rule"] = self.PLUGIN_PATH + "/" + route["rule"]
            except Exception as er:
                logging.error("Plugin %s: Unable to create route. Er: ", self.name, er)
                continue

            try:
                app.add_url_rule(defaults=defaults, **route)
            except Exception as er:
                logging.error("Plugin %s: Unable to activate. Er: ", self.name, er)
                continue

            logging.info("Plugin %s: activate", self.name)

    def run_scripts(self):
        for script in self.scripts:
            script().run()

