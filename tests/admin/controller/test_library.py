from nose.tools import (
    set_trace,
    eq_,
    assert_raises
)
import base64
import flask
import json
import urllib
from StringIO import StringIO
from werkzeug import ImmutableMultiDict, MultiDict
from api.admin.exceptions import *
from api.config import Configuration
from api.registry import (
    Registration,
    RemoteRegistry,
)
from core.facets import FacetConstants
from core.model import (
    AdminRole,
    ConfigurationSetting,
    create,
    ExternalIntegration,
    get_one,
    get_one_or_create,
    Library,
)
from core.testing import MockRequestsResponse
from api.admin.controller.library_settings import LibrarySettingsController
from test_controller import SettingsControllerTest

class TestLibrarySettings(SettingsControllerTest):

    def library_form(self, library, fields={}):

        defaults = {
            "uuid": library.uuid,
            "name": "The New York Public Library",
            "short_name": library.short_name,
            Configuration.WEBSITE_URL: "https://library.library/",
            Configuration.HELP_EMAIL: "help@example.com",
            Configuration.DEFAULT_NOTIFICATION_EMAIL_ADDRESS: "email@example.com"
        }
        defaults.update(fields)
        form = MultiDict(defaults.items())
        return form

    def test_libraries_get_with_no_libraries(self):
        # Delete any existing library created by the controller test setup.
        library = get_one(self._db, Library)
        if library:
            self._db.delete(library)

        with self.app.test_request_context("/"):
            response = self.manager.admin_library_settings_controller.process_get()
            eq_(response.get("libraries"), [])

    def test_libraries_get_with_multiple_libraries(self):
        # Delete any existing library created by the controller test setup.
        library = get_one(self._db, Library)
        if library:
            self._db.delete(library)

        l1 = self._library("Library 1", "L1")
        l2 = self._library("Library 2", "L2")
        l3 = self._library("Library 3", "L3")
        # L2 has some additional library-wide settings.
        ConfigurationSetting.for_library(Configuration.FEATURED_LANE_SIZE, l2).value = 5
        ConfigurationSetting.for_library(
            Configuration.DEFAULT_FACET_KEY_PREFIX + FacetConstants.ORDER_FACET_GROUP_NAME, l2
        ).value = FacetConstants.ORDER_RANDOM
        ConfigurationSetting.for_library(
            Configuration.ENABLED_FACETS_KEY_PREFIX + FacetConstants.ORDER_FACET_GROUP_NAME, l2
        ).value = json.dumps([FacetConstants.ORDER_TITLE, FacetConstants.ORDER_RANDOM])
        ConfigurationSetting.for_library(
            Configuration.LARGE_COLLECTION_LANGUAGES, l2
        ).value = json.dumps(["French"])
        # The admin only has access to L1 and L2.
        self.admin.remove_role(AdminRole.SYSTEM_ADMIN)
        self.admin.add_role(AdminRole.LIBRARIAN, l1)
        self.admin.add_role(AdminRole.LIBRARY_MANAGER, l2)

        with self.request_context_with_admin("/"):
            response = self.manager.admin_library_settings_controller.process_get()
            libraries = response.get("libraries")
            eq_(2, len(libraries))

            eq_(l1.uuid, libraries[0].get("uuid"))
            eq_(l2.uuid, libraries[1].get("uuid"))

            eq_(l1.name, libraries[0].get("name"))
            eq_(l2.name, libraries[1].get("name"))

            eq_(l1.short_name, libraries[0].get("short_name"))
            eq_(l2.short_name, libraries[1].get("short_name"))

            eq_({}, libraries[0].get("settings"))
            eq_(4, len(libraries[1].get("settings").keys()))
            settings = libraries[1].get("settings")
            eq_("5", settings.get(Configuration.FEATURED_LANE_SIZE))
            eq_(FacetConstants.ORDER_RANDOM,
                settings.get(Configuration.DEFAULT_FACET_KEY_PREFIX + FacetConstants.ORDER_FACET_GROUP_NAME))
            eq_([FacetConstants.ORDER_TITLE, FacetConstants.ORDER_RANDOM],
               settings.get(Configuration.ENABLED_FACETS_KEY_PREFIX + FacetConstants.ORDER_FACET_GROUP_NAME))
            eq_(["French"], settings.get(Configuration.LARGE_COLLECTION_LANGUAGES))

    def test_validate_geographic_areas(self):
        original_controller = self.manager.admin_library_settings_controller
        db = self._db
        class Mock(LibrarySettingsController):
            def __init__(self):
                self._db = db
                self.value = None

            def mock_find_location_through_registry(self, value):
                self.value = value
            def mock_find_location_through_registry_with_error(self, value):
                self.value = value
                return REMOTE_INTEGRATION_FAILED
            def mock_find_location_through_registry_success(self, value):
                self.value = value
                return "CA"

        controller = Mock()
        controller.find_location_through_registry = controller.mock_find_location_through_registry
        library = self._library()

        # Test invalid geographic input

        # Invalid US zipcode
        with self.request_context_with_admin("/", method="POST"):
            flask.request.form = self.library_form(
                library, {Configuration.LIBRARY_SERVICE_AREA: "00000"}
            )
            response = controller.process_post()
            eq_(response.uri, UNKNOWN_LOCATION.uri)
            eq_(response.detail, '"00000" is not a valid U.S. zipcode.')
            # The controller should have returned the problem detail without bothering to ask the registry.
            eq_(controller.value, None)

        # Invalid Canadian zipcode
        with self.request_context_with_admin("/", method="POST"):
            flask.request.form = self.library_form(
                library, {Configuration.LIBRARY_SERVICE_AREA: "X1Y"}
            )
            response = controller.process_post()
            eq_(response.uri, UNKNOWN_LOCATION.uri)
            eq_(response.detail, '"X1Y" is not a valid Canadian zipcode.')
            # The controller should have returned the problem detail without bothering to ask the registry.
            eq_(controller.value, None)

        # Invalid 2-letter abbreviation
        with self.request_context_with_admin("/", method="POST"):
            flask.request.form = self.library_form(
                library, {Configuration.LIBRARY_SERVICE_AREA: "ZZ"}
            )
            response = controller.process_post()
            eq_(response.uri, UNKNOWN_LOCATION.uri)
            eq_(response.detail, '"ZZ" is not a valid U.S. state or Canadian province abbreviation.')
            # The controller should have returned the problem detail without bothering to ask the registry.
            eq_(controller.value, None)

        # County with wrong state
        with self.request_context_with_admin("/", method="POST"):
            flask.request.form = self.library_form(
                library, {Configuration.LIBRARY_SERVICE_AREA: "Fairfield County, FL"}
            )
            response = controller.process_post()
            eq_(response.uri, UNKNOWN_LOCATION.uri)
            eq_(response.detail, 'Unable to locate "Fairfield County, FL".')
            # The controller should go ahead and call find_location_through_registry
            eq_(controller.value, "Fairfield County, FL")

        # City with wrong state
        with self.request_context_with_admin("/", method="POST"):
            flask.request.form = self.library_form(
                library, {Configuration.LIBRARY_SERVICE_AREA: "Albany, NJ"}
            )
            response = controller.process_post()
            eq_(response.uri, UNKNOWN_LOCATION.uri)
            eq_(response.detail, 'Unable to locate "Albany, NJ".')
            # The controller should go ahead and call find_location_through_registry
            eq_(controller.value, "Albany, NJ")

        # Can't connect to registry
        with self.request_context_with_admin("/", method="POST"):
            flask.request.form = self.library_form(
                library, {Configuration.LIBRARY_SERVICE_AREA: "Ontario"}
            )
            controller.find_location_through_registry = controller.mock_find_location_through_registry_with_error
            response = controller.process_post()
            eq_(controller.value, "Ontario")
            # The controller goes ahead and calls find_location_through_registry, but it can't connect to the registry.
            eq_(response.uri, REMOTE_INTEGRATION_FAILED.uri)

        # The registry successfully finds the place
        controller.find_location_through_registry = controller.mock_find_location_through_registry_success
        response = controller.validate_geographic_areas('["Ontario"]')
        eq_(response, '{"CA": ["Ontario"], "US": []}')

    def test_libraries_post_errors(self):
        with self.request_context_with_admin("/", method="POST"):
            flask.request.form = MultiDict([
                ("name", "Brooklyn Public Library"),
            ])
            response = self.manager.admin_library_settings_controller.process_post()
            eq_(response, MISSING_LIBRARY_SHORT_NAME)

        self.admin.remove_role(AdminRole.SYSTEM_ADMIN)
        with self.request_context_with_admin("/", method="POST"):
            flask.request.form = MultiDict([
                ("name", "Brooklyn Public Library"),
                ("short_name", "bpl"),
            ])
            assert_raises(AdminNotAuthorized,
              self.manager.admin_library_settings_controller.process_post)

        library = self._library()
        self.admin.add_role(AdminRole.LIBRARIAN, library)

        with self.request_context_with_admin("/", method="POST"):
            flask.request.form = MultiDict([
                ("uuid", library.uuid),
                ("name", "Brooklyn Public Library"),
                ("short_name", library.short_name),
            ])
            assert_raises(AdminNotAuthorized,
                self.manager.admin_library_settings_controller.process_post)

        self.admin.add_role(AdminRole.SYSTEM_ADMIN)
        with self.request_context_with_admin("/", method="POST"):
            flask.request.form = self.library_form(library, {"uuid": "1234"})
            response = self.manager.admin_library_settings_controller.process_post()
            eq_(response.uri, LIBRARY_NOT_FOUND.uri)

        with self.request_context_with_admin("/", method="POST"):
            flask.request.form = MultiDict([
                ("name", "Brooklyn Public Library"),
                ("short_name", library.short_name),
            ])
            response = self.manager.admin_library_settings_controller.process_post()
            eq_(response, LIBRARY_SHORT_NAME_ALREADY_IN_USE)

        bpl, ignore = get_one_or_create(
            self._db, Library, short_name="bpl"
        )
        with self.request_context_with_admin("/", method="POST"):
            flask.request.form = MultiDict([
                ("uuid", bpl.uuid),
                ("name", "Brooklyn Public Library"),
                ("short_name", library.short_name),
            ])
            response = self.manager.admin_library_settings_controller.process_post()
            eq_(response, LIBRARY_SHORT_NAME_ALREADY_IN_USE)

        with self.request_context_with_admin("/", method="POST"):
            flask.request.form = MultiDict([
                ("uuid", library.uuid),
                ("name", "The New York Public Library"),
                ("short_name", library.short_name),
            ])
            response = self.manager.admin_library_settings_controller.process_post()
            eq_(response.uri, INCOMPLETE_CONFIGURATION.uri)

        # Test a bad contrast ratio between the web foreground and
        # web background colors.
        with self.request_context_with_admin("/", method="POST"):
            flask.request.form = self.library_form(
                library, {Configuration.WEB_BACKGROUND_COLOR: "#000000",
                Configuration.WEB_FOREGROUND_COLOR: "#010101"}
            )
            response = self.manager.admin_library_settings_controller.process_post()
            eq_(response.uri, INVALID_CONFIGURATION_OPTION.uri)
            assert "contrast-ratio.com/#%23010101-on-%23000000" in response.detail

        # Test a list of web header links and a list of labels that
        # aren't the same length.
        library = self._library()
        with self.request_context_with_admin("/", method="POST"):
            flask.request.form = MultiDict([
                ("uuid", library.uuid),
                ("name", "The New York Public Library"),
                ("short_name", library.short_name),
                (Configuration.WEBSITE_URL, "https://library.library/"),
                (Configuration.DEFAULT_NOTIFICATION_EMAIL_ADDRESS, "email@example.com"),
                (Configuration.HELP_EMAIL, "help@example.com"),
                (Configuration.WEB_HEADER_LINKS, "http://library.com/1"),
                (Configuration.WEB_HEADER_LINKS, "http://library.com/2"),
                (Configuration.WEB_HEADER_LABELS, "One"),
            ])
            response = self.manager.admin_library_settings_controller.process_post()
            eq_(response.uri, INVALID_CONFIGURATION_OPTION.uri)


    def test_libraries_post_create(self):
        class TestFileUpload(StringIO):
            headers = { "Content-Type": "image/png" }
        image_data = '\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x01\x03\x00\x00\x00%\xdbV\xca\x00\x00\x00\x06PLTE\xffM\x00\x01\x01\x01\x8e\x1e\xe5\x1b\x00\x00\x00\x01tRNS\xcc\xd24V\xfd\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82'

        with self.request_context_with_admin("/", method="POST"):
            flask.request.form = MultiDict([
                ("name", "The New York Public Library"),
                ("short_name", "nypl"),
                ("library_description", "Short description of library"),
                (Configuration.WEBSITE_URL, "https://library.library/"),
                (Configuration.TINY_COLLECTION_LANGUAGES, ['ger']),
                (Configuration.LIBRARY_SERVICE_AREA, ['06759', 'everywhere', 'MD', 'Boston, MA']),
                (Configuration.LIBRARY_FOCUS_AREA, ['V5K', 'Broward County, FL', 'QC']),
                (Configuration.DEFAULT_NOTIFICATION_EMAIL_ADDRESS, "email@example.com"),
                (Configuration.HELP_EMAIL, "help@example.com"),
                (Configuration.FEATURED_LANE_SIZE, "5"),
                (Configuration.DEFAULT_FACET_KEY_PREFIX + FacetConstants.ORDER_FACET_GROUP_NAME,
                 FacetConstants.ORDER_RANDOM),
                (Configuration.ENABLED_FACETS_KEY_PREFIX + FacetConstants.ORDER_FACET_GROUP_NAME + "_" + FacetConstants.ORDER_TITLE,
                 ''),
                (Configuration.ENABLED_FACETS_KEY_PREFIX + FacetConstants.ORDER_FACET_GROUP_NAME + "_" + FacetConstants.ORDER_RANDOM,
                 ''),
            ])
            flask.request.files = MultiDict([
                (Configuration.LOGO, TestFileUpload(image_data)),
            ])
            response = self.manager.admin_library_settings_controller.process_post()
            eq_(response.status_code, 201)

        library = get_one(self._db, Library, short_name="nypl")
        eq_(library.uuid, response.response[0])
        eq_(library.name, "The New York Public Library")
        eq_(library.short_name, "nypl")
        eq_("5", ConfigurationSetting.for_library(Configuration.FEATURED_LANE_SIZE, library).value)
        eq_(FacetConstants.ORDER_RANDOM,
            ConfigurationSetting.for_library(
                Configuration.DEFAULT_FACET_KEY_PREFIX + FacetConstants.ORDER_FACET_GROUP_NAME,
                library).value)
        eq_(json.dumps([FacetConstants.ORDER_TITLE, FacetConstants.ORDER_RANDOM]),
            ConfigurationSetting.for_library(
                Configuration.ENABLED_FACETS_KEY_PREFIX + FacetConstants.ORDER_FACET_GROUP_NAME,
                library).value)
        eq_("data:image/png;base64,%s" % base64.b64encode(image_data),
            ConfigurationSetting.for_library(Configuration.LOGO, library).value)
        eq_('{"CA": [], "US": [{"06759": "Litchfield, CT"}, "everywhere", "MD", "Boston, MA"]}',
            ConfigurationSetting.for_library(Configuration.LIBRARY_SERVICE_AREA, library).value)
        eq_('{"CA": [{"V5K": "Vancouver (North Hastings- Sunrise), British Columbia"}, "QC"], "US": ["Broward County, FL"]}',
            ConfigurationSetting.for_library(Configuration.LIBRARY_FOCUS_AREA, library).value)

        # When the library was created, default lanes were also created
        # according to its language setup. This library has one tiny
        # collection (not a good choice for a real library), so only
        # two lanes were created: "Other Languages" and then "German"
        # underneath it.
        [german, other_languages] = sorted(
            library.lanes, key=lambda x: x.display_name
        )
        eq_(None, other_languages.parent)
        eq_(['ger'], other_languages.languages)
        eq_(other_languages, german.parent)
        eq_(['ger'], german.languages)

    def test_libraries_post_edit(self):
        # A library already exists.
        library = self._library("New York Public Library", "nypl")

        ConfigurationSetting.for_library(Configuration.FEATURED_LANE_SIZE, library).value = 5
        ConfigurationSetting.for_library(
            Configuration.DEFAULT_FACET_KEY_PREFIX + FacetConstants.ORDER_FACET_GROUP_NAME, library
        ).value = FacetConstants.ORDER_RANDOM
        ConfigurationSetting.for_library(
            Configuration.ENABLED_FACETS_KEY_PREFIX + FacetConstants.ORDER_FACET_GROUP_NAME, library
        ).value = json.dumps([FacetConstants.ORDER_TITLE, FacetConstants.ORDER_RANDOM])
        ConfigurationSetting.for_library(
            Configuration.LOGO, library
        ).value = "A tiny image"

        with self.request_context_with_admin("/", method="POST"):
            flask.request.form = MultiDict([
                ("uuid", library.uuid),
                ("name", "The New York Public Library"),
                ("short_name", "nypl"),
                (Configuration.FEATURED_LANE_SIZE, "20"),
                (Configuration.MINIMUM_FEATURED_QUALITY, "0.9"),
                (Configuration.WEBSITE_URL, "https://library.library/"),
                (Configuration.DEFAULT_NOTIFICATION_EMAIL_ADDRESS, "email@example.com"),
                (Configuration.HELP_EMAIL, "help@example.com"),
                (Configuration.DEFAULT_FACET_KEY_PREFIX + FacetConstants.ORDER_FACET_GROUP_NAME,
                 FacetConstants.ORDER_AUTHOR),
                (Configuration.ENABLED_FACETS_KEY_PREFIX + FacetConstants.ORDER_FACET_GROUP_NAME + "_" + FacetConstants.ORDER_AUTHOR,
                 ''),
                (Configuration.ENABLED_FACETS_KEY_PREFIX + FacetConstants.ORDER_FACET_GROUP_NAME + "_" + FacetConstants.ORDER_RANDOM,
                 ''),
            ])
            flask.request.files = MultiDict([])
            response = self.manager.admin_library_settings_controller.process_post()
            eq_(response.status_code, 200)

        library = get_one(self._db, Library, uuid=library.uuid)

        eq_(library.uuid, response.response[0])
        eq_(library.name, "The New York Public Library")
        eq_(library.short_name, "nypl")

        # The library-wide settings were updated.
        def val(x):
            return ConfigurationSetting.for_library(x, library).value
        eq_("https://library.library/", val(Configuration.WEBSITE_URL))
        eq_("email@example.com", val(Configuration.DEFAULT_NOTIFICATION_EMAIL_ADDRESS))
        eq_("help@example.com", val(Configuration.HELP_EMAIL))
        eq_("20", val(Configuration.FEATURED_LANE_SIZE))
        eq_("0.9", val(Configuration.MINIMUM_FEATURED_QUALITY))
        eq_(FacetConstants.ORDER_AUTHOR,
            val(Configuration.DEFAULT_FACET_KEY_PREFIX + FacetConstants.ORDER_FACET_GROUP_NAME)
        )
        eq_(json.dumps([FacetConstants.ORDER_AUTHOR, FacetConstants.ORDER_RANDOM]),
            val(Configuration.ENABLED_FACETS_KEY_PREFIX + FacetConstants.ORDER_FACET_GROUP_NAME)
        )

        # The library-wide logo was not updated and has been left alone.
        eq_("A tiny image",
            ConfigurationSetting.for_library(Configuration.LOGO, library).value
        )

    def test_library_delete(self):
        library = self._library()

        with self.request_context_with_admin("/", method="DELETE"):
            self.admin.remove_role(AdminRole.SYSTEM_ADMIN)
            assert_raises(AdminNotAuthorized,
                          self.manager.admin_library_settings_controller.process_delete,
                          library.uuid)

            self.admin.add_role(AdminRole.SYSTEM_ADMIN)
            response = self.manager.admin_library_settings_controller.process_delete(library.uuid)
            eq_(response.status_code, 200)

        library = get_one(self._db, Library, uuid=library.uuid)
        eq_(None, library)

    def test_find_location_through_registry(self):
        library = self._default_library
        controller = self.manager.admin_library_settings_controller
        original_ask_registry = controller.ask_registry
        get = self.do_request
        test = self
        class Mock(LibrarySettingsController):
            called_with = []
            def ask_registry(self, service_area_object):
                places = {"US": ["Chicago"], "CA": ["Ontario"]}
                service_area_info = json.loads(urllib.unquote(service_area_object))
                nation = service_area_info.keys()[0]
                city_or_county = service_area_info.values()[0]
                if city_or_county == "ERROR":
                    test.responses.append(MockRequestsResponse(502))
                elif city_or_county in places[nation]:
                    self.called_with.append(service_area_info)
                    test.responses.append(MockRequestsResponse(200, content=json.dumps(dict(unknown=None, ambiguous=None))))
                else:
                    self.called_with.append(service_area_info)
                    test.responses.append(MockRequestsResponse(200, content=json.dumps(dict(unknown=[city_or_county]))))
                return original_ask_registry(service_area_object, get)

        mock_controller = Mock(controller)

        self._registry("https://registry_url")

        us_response = mock_controller.find_location_through_registry("Chicago")
        eq_(len(mock_controller.called_with), 1)
        eq_({"US": "Chicago"}, mock_controller.called_with[0])
        eq_(us_response, "US")

        mock_controller.called_with = []

        ca_response = mock_controller.find_location_through_registry("Ontario")
        eq_(len(mock_controller.called_with), 2)
        eq_({"US": "Ontario"}, mock_controller.called_with[0])
        eq_({"CA": "Ontario"}, mock_controller.called_with[1])
        eq_(ca_response, "CA")

        mock_controller.called_with = []

        nowhere_response = mock_controller.find_location_through_registry("Not a real place")
        eq_(len(mock_controller.called_with), 2)
        eq_({"US": "Not a real place"}, mock_controller.called_with[0])
        eq_({"CA": "Not a real place"}, mock_controller.called_with[1])
        eq_(nowhere_response, None)

        error_response = mock_controller.find_location_through_registry("ERROR")
        eq_(error_response.detail, "Unable to contact the registry at https://registry_url.")
        eq_(error_response.status_code, 502)

    def test_ask_registry(self):
        controller = self.manager.admin_library_settings_controller

        registry_1 = self._registry("https://registry_1_url")
        registry_2 = self._registry("https://registry_2_url")
        registry_3 = self._registry("https://registry_3_url")

        true_response = MockRequestsResponse(200, content="{}")
        unknown_response = MockRequestsResponse(200, content='{"unknown": "place"}')
        ambiguous_response = MockRequestsResponse(200, content='{"ambiguous": "place"}')
        problem_response = MockRequestsResponse(404)

        # Registry 1 knows about the place
        self.responses.append(true_response)
        response_1 = controller.ask_registry(json.dumps({"CA": "Ontario"}), self.do_request)
        eq_(response_1, True)
        eq_(len(self.requests), 1)
        request_1 = self.requests.pop()
        eq_(request_1[0], 'https://registry_1_url/coverage?coverage={"CA": "Ontario"}')

        # Registry 1 says the place is unknown, but Registry 2 finds it.
        self.responses.append(true_response)
        self.responses.append(unknown_response)
        response_2 = controller.ask_registry(json.dumps({"CA": "Ontario"}), self.do_request)
        eq_(response_2, True)
        eq_(len(self.requests), 2)
        request_2 = self.requests.pop()
        eq_(request_2[0], 'https://registry_2_url/coverage?coverage={"CA": "Ontario"}')
        request_1 = self.requests.pop()
        eq_(request_1[0], 'https://registry_1_url/coverage?coverage={"CA": "Ontario"}')

        # Registry_1 says the place is ambiguous and Registry_2 says it's unknown, but Registry_3 finds it.
        self.responses.append(true_response)
        self.responses.append(unknown_response)
        self.responses.append(ambiguous_response)
        response_3 = controller.ask_registry(json.dumps({"CA": "Ontario"}), self.do_request)
        eq_(response_3, True)
        eq_(len(self.requests), 3)
        request_3 = self.requests.pop()
        eq_(request_3[0], 'https://registry_3_url/coverage?coverage={"CA": "Ontario"}')
        request_2 = self.requests.pop()
        eq_(request_2[0], 'https://registry_2_url/coverage?coverage={"CA": "Ontario"}')
        request_1 = self.requests.pop()
        eq_(request_1[0], 'https://registry_1_url/coverage?coverage={"CA": "Ontario"}')

        # Registry 1 returns a problem detail, but Registry 2 finds the place
        self.responses.append(true_response)
        self.responses.append(problem_response)
        response_4 = controller.ask_registry(json.dumps({"CA": "Ontario"}), self.do_request)
        eq_(response_4, True)
        eq_(len(self.requests), 2)
        request_2 = self.requests.pop()
        eq_(request_2[0], 'https://registry_2_url/coverage?coverage={"CA": "Ontario"}')
        request_1 = self.requests.pop()
        eq_(request_1[0], 'https://registry_1_url/coverage?coverage={"CA": "Ontario"}')

        # Registry 1 returns a problem detail and the other two registries can't find the place
        self.responses.append(unknown_response)
        self.responses.append(ambiguous_response)
        self.responses.append(problem_response)
        response_5 = controller.ask_registry(json.dumps({"CA": "Ontario"}), self.do_request)
        eq_(response_5.status_code, 502)
        eq_(response_5.detail, "Unable to contact the registry at https://registry_1_url.")
        eq_(len(self.requests), 3)
        request_3 = self.requests.pop()
        eq_(request_3[0], 'https://registry_3_url/coverage?coverage={"CA": "Ontario"}')
        request_2 = self.requests.pop()
        eq_(request_2[0], 'https://registry_2_url/coverage?coverage={"CA": "Ontario"}')
        request_1 = self.requests.pop()
        eq_(request_1[0], 'https://registry_1_url/coverage?coverage={"CA": "Ontario"}')

    def _registry(self, url):
        integration, is_new = create(
            self._db, ExternalIntegration, protocol=ExternalIntegration.OPDS_REGISTRATION, goal=ExternalIntegration.DISCOVERY_GOAL
        )
        integration.url = url
        return RemoteRegistry(integration)
