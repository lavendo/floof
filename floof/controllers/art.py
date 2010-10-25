import hashlib
import logging
import random

import magic
import PIL.Image
from pylons import config, request, response, session, tmpl_context as c, url
from pylons.controllers.util import abort, redirect
from sqlalchemy.orm.exc import NoResultFound
import wtforms.form, wtforms.fields, wtforms.validators

from floof.lib import helpers
from floof.lib.base import BaseController, render
from floof.model import meta
from floof import model

log = logging.getLogger(__name__)

def get_number_of_colors(image):
    """Does what it says on the tin.

    This attempts to return the number of POSSIBLE colors in the image, not the
    number of colors actually used.  In the case of a paletted image, PIL is
    often limited to only returning the actual number of colors.  But that's
    usually what we mean for palettes, so eh.

    But full-color images will always return 16777216.  Alpha doesn't count, so
    RGBA is still 24-bit color.
    """
    # See http://www.pythonware.com/library/pil/handbook/concepts.htm for list
    # of all possible PIL modes
    mode = image.mode
    if mode == '1':
        return 2
    elif mode == 'L':
        return 256
    elif mode == 'P':
        # This is sort of (a) questionable and (b) undocumented, BUT:
        # palette.getdata() returns a tuple of mode and raw bytes.  The raw
        # bytes are rgb encoded as three bytes each, so its length is three
        # times the number of palette entries.
        palmode, paldata = image.palette.getdata()
        return len(paldata) / 3
    elif mode in ('RGB', 'RGBA', 'CMYK', 'YCbCr', 'I', 'F',
        'LA', 'RGBX', 'RGBa'):
        return 2 ** 24
    else:
        raise ValueError("Unknown palette mode, argh!")

class UploadArtworkForm(wtforms.form.Form):
    file = wtforms.fields.FileField(u'')
    title = wtforms.fields.TextField(u'Title')
    relationship_by_for = wtforms.fields.RadioField(u'',
        [wtforms.validators.required()],
        choices=[
            (u'by',  u"by me: I'm the artist; I created this!"),
            (u'for', u"for me: I commissioned this, or it was a gift specifically for me"),
        ],
    )
    relationship_of = wtforms.fields.BooleanField(u"of me: I'm depicted in this artwork")

class ArtController(BaseController):
    HASH_BUFFER_SIZE = 524288  # half a meg
    MAX_ASPECT_RATIO = 2

    def upload(self):
        """Uploads something.  Sort of important, you know."""
        if not c.user.can('upload_art'):
            abort(403)

        c.form = UploadArtworkForm(request.POST)

        if request.method == 'POST' and c.form.validate():
            # Grab the file
            storage = config['filestore']
            uploaded_file = request.POST.get('file')

            try:
                fileobj = uploaded_file.file
            except AttributeError:
                c.form.file.errors.append("Please select a file to upload!")
                return render('/art/upload.mako')

            # Figure out mimetype (and if we even support it)
            mimetype = magic.Magic(mime=True).from_buffer(fileobj.read(1024)) \
                .decode('ascii')
            if mimetype not in (u'image/png', u'image/gif', u'image/jpeg'):
                c.form.file.errors.append("Only PNG, GIF, and JPEG are supported at the moment.")
                return render('/art/upload.mako')

            # Hash the thing
            hasher = hashlib.sha256()
            file_size = 0
            fileobj.seek(0)
            while True:
                buffer = fileobj.read(self.HASH_BUFFER_SIZE)
                if not buffer:
                    break

                file_size += len(buffer)
                hasher.update(buffer)
            hash = hasher.hexdigest().decode('ascii')

            # Assert that the thing is unique
            existing_artwork = meta.Session.query(model.Artwork) \
                .filter_by(hash = hash) \
                .all()
            if existing_artwork:
                # XXX flash here
                helpers.flash(u'This artwork has already been uploaded.',
                    level=u'warning', icon=u'image-import')
                redirect(helpers.art_url(existing_artwork[0]))

            ### By now, all error-checking should be done.

            # OK, store the file.  Reset the file object first!
            fileobj.seek(0)
            storage.put(hash, fileobj)

            # Open the image, determine its size, and generate a thumbnail
            fileobj.seek(0)
            image = PIL.Image.open(fileobj)
            width, height = image.size

            # Thumbnailin'
            thumbnail_size = int(config['thumbnail_size'])
            # To avoid super-skinny thumbnails, don't let the aspect ratio go
            # beyond 2
            height = min(height, width * self.MAX_ASPECT_RATIO)
            width = min(width, height * self.MAX_ASPECT_RATIO)
            # crop() takes left, top, right, bottom
            cropped_image = image.crop((0, 0, width, height))
            # And resize...  if necessary
            if width > thumbnail_size or height > thumbnail_size:
                if width > height:
                    new_size = (thumbnail_size, height * thumbnail_size // width)
                else:
                    new_size = (width * thumbnail_size // height, thumbnail_size)

                thumbnail_image = cropped_image.resize(
                    new_size, PIL.Image.ANTIALIAS)

            else:
                thumbnail_image = cropped_image

            # Dump the thumbnail in a buffer and save it, too
            # XXX find a better storage medium for these perhaps!
            from cStringIO import StringIO
            buf = StringIO()
            if mimetype == u'image/png':
                thumbnail_format = 'PNG'
            elif mimetype == u'image/gif':
                thumbnail_format = 'GIF'
            elif mimetype == u'image/jpeg':
                thumbnail_format = 'JPEG'
            thumbnail_image.save(buf, thumbnail_format)
            buf.seek(0)
            storage.put(hash + '.thumbnail', buf)

            # Deal with user-supplied metadata
            # nb: it's perfectly valid to have no title
            title = c.form.title.data.strip()

            # Stuff it all in the db
            general_data = dict(
                title = title,
                hash = hash,
                uploader = c.user,
                original_filename = uploaded_file.filename,
                mime_type = mimetype,
                file_size = file_size,
            )
            artwork = model.MediaImage(
                height = height,
                width = width,
                number_of_colors = get_number_of_colors(image),
                **general_data
            )

            # Associate the uploader as artist or recipient
            artwork.user_artwork.append(
                model.UserArtwork(
                    user_id = c.user.id,
                    relationship_type = c.form.relationship_by_for.data,
                )
            )
            # Also as a participant if appropriate
            if c.form.relationship_of.data:
                artwork.user_artwork.append(
                    model.UserArtwork(
                        user_id = c.user.id,
                        relationship_type = u'of',
                    )
                )

            meta.Session.add(artwork)
            meta.Session.commit()

            helpers.flash(u'Uploaded!',
                level=u'success', icon=u'image--plus')
            redirect(helpers.art_url(artwork))

        else:
            return render('/art/upload.mako')

    def gallery(self):
        """Main gallery; provides browsing through absolutely everything we've
        got.
        """
        c.artwork = meta.Session.query(model.Artwork).all()
        return render('/art/gallery.mako')

    def view(self, id):
        """View a single item of artwork."""
        c.artwork = meta.Session.query(model.Artwork).get(id)
        if not c.artwork:
            abort(404)

        storage = config['filestore']
        c.artwork_url = storage.url(c.artwork.hash)

        return render('/art/view.mako')