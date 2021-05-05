import json

import webpub_manifest_parser.odl.ast as odl_ast
from webpub_manifest_parser.opds2.registry import OPDS2LinkRelationsRegistry

from api.odl import ODLAPI
from core.metadata_layer import LicenseData, FormatData
from core.model import Edition, RightsStatus, MediaTypes, DeliveryMechanism
from core.opds2_import import OPDS2Importer, OPDS2ImportMonitor
from core.util import first_or_default


class ODL2API(ODLAPI):
    NAME = "ODL + OPDS 2.x"


class ODL2Importer(OPDS2Importer):
    """Import information and formats from an ODL feed.

    The only change from OPDSImporter is that this importer extracts
    format information from 'odl:license' tags.
    """
    NAME = ODL2API.NAME

    def _extract_publication_metadata(self, feed, publication, data_source_name):
        """Extract a Metadata object from webpub-manifest-parser's publication.

        :param publication: Feed object
        :type publication: opds2_ast.OPDS2Feed

        :param publication: Publication object
        :type publication: opds2_ast.OPDS2Publication

        :param data_source_name: Data source's name
        :type data_source_name: str

        :return: Publication's metadata
        :rtype: Metadata
        """
        metadata = super(ODL2Importer, self)._extract_publication_metadata(feed, publication, data_source_name)
        formats = []
        licenses = []
        licenses_owned = 0
        licenses_available = 0
        medium = None

        if publication.licenses:
            for license in publication.licenses:
                identifier = license.metadata.identifier
                format = first_or_default(license.metadata.formats)

                if not medium:
                    medium = Edition.medium_from_media_type(format)

                if license.metadata.protection:
                    for drm_scheme in license.metadata.protection.formats or [None]:
                        formats.append(
                            FormatData(
                                content_type=format,
                                drm_scheme=drm_scheme,
                                rights_uri=RightsStatus.IN_COPYRIGHT,
                            )
                        )

                expires = None
                remaining_checkouts = None
                available_checkouts = None
                concurrent_checkouts = None

                checkout_link = first_or_default(license.links.get_by_rel(OPDS2LinkRelationsRegistry.BORROW.key))
                if checkout_link:
                    checkout_link = checkout_link.href

                odl_status_link = first_or_default(license.links.get_by_rel(OPDS2LinkRelationsRegistry.SELF.key))
                if odl_status_link:
                    odl_status_link = odl_status_link.href

                if odl_status_link:
                    _, _, response = self.http_get(odl_status_link, headers={})
                    status = json.loads(response)
                    checkouts = status.get("checkouts", {})
                    remaining_checkouts = checkouts.get("left")
                    available_checkouts = checkouts.get("available")

                if license.metadata.terms:
                    expires = license.metadata.terms.expires
                    concurrent_checkouts = license.metadata.terms.concurrency

                licenses_owned += int(concurrent_checkouts or 0)
                licenses_available += int(available_checkouts or 0)

                licenses.append(LicenseData(
                    identifier=identifier,
                    checkout_url=checkout_link,
                    status_url=odl_status_link,
                    expires=expires,
                    remaining_checkouts=remaining_checkouts,
                    concurrent_checkouts=concurrent_checkouts,
                ))

        metadata.circulation.licenses_owned = licenses_owned
        metadata.circulation.licenses_available = licenses_available
        metadata.circulation.licenses = licenses
        metadata.circulation.formats.extend(formats)

        return metadata


class ODL2ImportMonitor(OPDS2ImportMonitor):
    """Import information from an ODL feed."""
    PROTOCOL = ODL2Importer.NAME
    SERVICE_NAME = "ODL 2.x Import Monitor"
