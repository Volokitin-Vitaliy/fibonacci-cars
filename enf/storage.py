from django.contrib.staticfiles.storage import ManifestStaticFilesStorage


class StaticStorage(ManifestStaticFilesStorage):
    """Static files get a content hash in their name (site.3f2a1c.css) after
    collectstatic, so browsers can cache them for a year and still see every update.
    Before collectstatic has run (tests, local runs) plain names are used."""

    manifest_strict = False

    def stored_name(self, name):
        try:
            return super().stored_name(name)
        except ValueError:  # not collected yet
            return name
