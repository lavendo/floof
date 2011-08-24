import os, os.path

from floof import model
from floof.model import meta
from floof.tests import *
import floof.tests.sim as sim

class TestArtController(TestController):
    def file_contents(self, filename):
        """Returns a file stored in the test directory."""
        here, _ = os.path.split(__file__)
        path = os.path.join(here, filename)
        return open(path).read()


    @classmethod
    def setup_class(cls):
        """Creates a user to be used as a fake login."""
        cls.user = sim.sim_user()
        meta.Session.commit()

        # Force a refresh of the user, to get id populated
        # XXX surely there's a better way!
        meta.Session.refresh(cls.user)


    def test_gallery(self):
        """Test loading the main art page."""
        response = self.app.get(url(controller='art', action='gallery'))
        # Test response...

    def test_happyday_upload_png(self):
        """Test that uploading a PNG works correctly."""
        png = self.file_contents('pk.engiveer.png')
        response = self.app.post(
            url(controller='art', action='upload'),
            params=[
                ('title', u"test title"),
                ('relationship', u'by'),
                ('relationship', u'of'),
            ],
            upload_files=(
                ('file', 'pk.engiveer.png', png),
            ),
            extra_environ={'tests.user_id': self.user.id},
        )

        # Find the new image
        art = meta.Session.query(model.Artwork) \
            .order_by(model.Artwork.id.desc()) \
            .limit(1) \
            .first()

        # Make sure it looks like it should!
        assert art.title == u'test title'
        assert art.media_type == u'image'
        assert art.original_filename == u'pk.engiveer.png'
        assert art.file_size == 8363
        assert art.uploader_user_id == self.user.id
        # Image stats
        assert art.height == 500
        assert art.width == 400
        assert art.number_of_colors == 10
        assert art.frames == None
        assert art.length == None
        assert art.quality == None

        # Check on relationships
        relationships = art.user_artwork
        assert len(relationships) == 2
        assert set(_.relationship_type for _ in relationships) == \
            set([u'by', u'of'])

        # Response oughta have a redirect
        assert 'location' in response.headers
        location = response.headers['location']
        # And it should have the title in the URL
        assert location.endswith(u';test-title')

        # Test viewing the new artwork
        response = self.app.get(url(controller='art', action='view', id=art.id))


    def test_sadday_upload_junk(self):
        """Test that junk files are rejected."""

