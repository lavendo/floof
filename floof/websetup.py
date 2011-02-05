"""Setup the floof application"""
import logging
import os

import pylons.test

from floof.config.environment import load_environment
from floof.model import meta
from floof import model

from datetime import datetime, timedelta
import OpenSSL.crypto as ssl

log = logging.getLogger(__name__)

def setup_app(command, conf, vars):
    """Place any commands to setup floof here"""
    # Don't reload the app if it was loaded under the testing environment
    if not pylons.test.pylonsapp:
            load_environment(conf.global_conf, conf.local_conf)

    ### DB stuff
    meta.metadata.bind = meta.engine

    _, conf_file = os.path.split(conf.filename)
    if conf_file == 'test.ini':
        # Drop all existing tables during a test
        meta.metadata.drop_all(checkfirst=True)

    # Create the tables if they don't already exist
    meta.metadata.create_all(checkfirst=True)

    # Add canonical privileges and roles
    privileges = dict(
        (name, model.Privilege(name=name, description=description))
        for name, description in [
            (u'admin.view',         u'Can view administrative tools/panel'),
            (u'art.upload',         u'Can upload art'),
            (u'art.rate',           u'Can rate art'),
            (u'comments.add',       u'Can post comments'),
            (u'tags.add',           u'Can add tags with no restrictions'),
            (u'tags.remove',        u'Can remove tags with no restrictions'),
        ]
    )

    base_user = model.Role(
        name=u'user',
        description=u'Basic user',
        privileges=[privileges[priv] for priv in [
            u'art.upload', u'art.rate', u'comments.add', u'tags.add', u'tags.remove',
        ]],
    )
    admin_user = model.Role(
        name=u'admin',
        description=u'Administrator',
        privileges=privileges.values()
    )

    meta.Session.add_all([base_user, admin_user])
    meta.Session.commit()

    ### Client SSL/TLS certificate stuff
    # Generate the CA.  Attempt to load it from file first.
    generate_ca = True
    cert_dir = conf.local_conf['client_cert_dir']
    for filename in ['ca.pem', 'ca.key']:
        filepath = os.path.join(cert_dir, filename)
        if os.path.isfile(filepath):
            generate_ca = False
            break
    if generate_ca:
        ca_cert, ca_key, serial, bits, begin, expire = model.Certificate.make_cert(
                site_title=conf.local_conf['site_title'],
                ca=True,
                bits=2048,
                days=10 * 365 + 3,
                digest='sha1',
                )
        if not os.path.isdir(cert_dir):
            os.makedirs(cert_dir)
        with open(os.path.join(cert_dir, 'ca.key'), 'w') as f:
            f.write(ssl.dump_privatekey(ssl.FILETYPE_PEM, ca_key))
        with open(os.path.join(cert_dir, 'ca.pem'), 'w') as f:
            f.write(ssl.dump_certificate(ssl.FILETYPE_PEM, ca_cert))
        print """  New SSL Client Certificate CA generated at {0}
  ENSURE that {1} has appropriately restrictive access permissions!""".format(
                os.path.join(cert_dir, 'ca.pem'),
                os.path.join(cert_dir, 'ca.key'),
                )
    else:
        print "  Encountered existing CA certificate file {0}".format(filepath)
        # Breifly test the found files
        with open(os.path.join(cert_dir, 'ca.key'), 'rU') as f:
            ca_key = ssl.load_privatekey(ssl.FILETYPE_PEM, f.read())
        with open(os.path.join(cert_dir, 'ca.pem'), 'rU') as f:
            ca_cert = ssl.load_certificate(ssl.FILETYPE_PEM, f.read())
        print "  Will use this file as the SSL Client Certificate CA."
