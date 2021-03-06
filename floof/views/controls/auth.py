# encoding: utf8
import logging

from pyramid.httpexceptions import HTTPSeeOther
from pyramid.security import effective_principals
from pyramid.view import view_config
import wtforms
from wtforms.ext.sqlalchemy.fields import QuerySelectMultipleField

from floof import model
from floof.forms import FloofForm
from floof.lib.persona import PersonaError
from floof.lib.persona import flash_persona_error, verify_persona
from floof.lib.openid_ import OpenIDError, openid_begin, openid_end

log = logging.getLogger(__name__)


# XXX this all needs cleaning up, and some ajax, and whatever.
# XXX two forms on one page also raises questions about how best to handle invalid forms
class AddOpenIDForm(FloofForm):
    new_openid = wtforms.TextField(u'New OpenID', [wtforms.validators.Required()])


class RemoveOpenIDForm(FloofForm):
    openids = QuerySelectMultipleField(u'Remove OpenIDs', get_label=lambda row: row.url)

    def validate_openids(form, field):
        if not field.data:
            raise wtforms.ValidationError('You must select at least one OpenID identity URL to delete.')

        user = form.request.user
        total_ids = len(user.identity_urls) + len(user.identity_emails)
        if len(field.data) >= total_ids:
            raise wtforms.ValidationError(
                    'You must keep at least either one OpenID identity URL '
                    'or one Persona identity email address.')

        # XXX less hackish way to do this without adding an attr to
        # Authenticizer for every freakin property of the session's auth?
        curr_openid_url = form.request.auth.state.get('openid_url')
        if curr_openid_url in [obj.url for obj in field.data]:
            raise wtforms.ValidationError(
                    'You cannot remove the OpenID identity URL with which you '
                    'are currently logged in.')


class RemovePersonaForm(FloofForm):
    addrs = QuerySelectMultipleField(u'Remove Personas', get_label=lambda row: row.email)

    def validate_addrs(form, field):
        if not field.data:
            raise wtforms.ValidationError(
                    'You must select at least one Persona identity email '
                    'address to delete.')

        user = form.request.user
        total_ids = len(user.identity_urls) + len(user.identity_emails)
        if len(field.data) >= total_ids:
            raise wtforms.ValidationError(
                    'You must keep at least either one Persona identity '
                    'email address or one OpenID identity URL.')

        # XXX see RemoveOpenIDForm.validate_openids
        curr_addr = form.request.auth.persona_addr
        if curr_addr in [obj.email for obj in field.data]:
            raise wtforms.ValidationError(
                    'You cannot remove the Persona identity email address '
                    'with which you are currently logged in.')


class AuthenticationForm(FloofForm):
    cert_auth = wtforms.fields.SelectField(u'Cert Auth Method', choices=[
            (u'disabled', u'Disabled (default)'),
            (u'allowed', u'Allow for login'),
            (u'sensitive_required', u'Require for Sensitive Operations only'),
            (u'required', u'Require for login'),
            ])

    def validate_cert_auth(form, field):
        request = form.request
        if field.data in ['required', 'sensitive_required']:
            if not request.user.valid_certificates:
                raise wtforms.ValidationError('You cannot make a selection '
                        'that requires an SSL certificate to log in or to '
                        'change this setting while you have no valid SSL '
                        'certificates registered against your account.')
            if not 'trusted:cert' in effective_principals(request):
                raise wtforms.ValidationError('To prevent locking yourself '
                        'out, you cannot make a selection that requires an '
                        'SSL certificate to log in or to change this '
                        'setting without first loading this page while the '
                        'certificate is installed in your browser and being '
                        'successfully sent to the site.')


@view_config(
    route_name='controls.persona',
    permission='auth.persona',
    request_method='GET',
    renderer='account/controls/persona.mako')
def persona(context, request):
    user = request.user
    form = RemovePersonaForm(request)
    form.addrs.query = model.session.query(model.IdentityEmail).with_parent(user)

    return {'form': form}


# XXX: Currently not being hit by the Persona address addition flow.
def persona_add(context, request):
    next_url = request.route_url('controls.persona')

    def fail(msg=None):
        if msg:
            request.session.flash(msg, level=u'error', icon='key--exclamation')
        return next_url

    post = request.stash['post'] if request.stash else request.POST
    assertion = post.get('assertion')

    try:
        data = verify_persona(assertion, request)
    except PersonaError as e:
        flash_persona_error(e, request)
        return fail()

    email = data.get('email')
    if not email:
        return fail("Persona authentication failed.")

    extant_email = model.session.query(model.IdentityEmail) \
        .filter_by(email=email) \
        .limit(1).first()

    if extant_email:
        if extant_email.user == request.user:
            other_account = 'your account'
        else:
            other_account = "the account '{0}'".format(extant_email.user.name)
        return fail("The email address '{0}' already belongs to {1}."
                    .format(email, other_account))

    persona_id = model.IdentityEmail(email=email)
    request.user.identity_emails.append(persona_id)
    request.session.flash("Added Persona email address '{0}'".format(email),
                          level=u'success', icon='user')

    return  next_url


@view_config(
    route_name='controls.persona.add',
    permission='auth.persona',
    request_method='POST',
    xhr=True,
    renderer='json')
def persona_add_xhr(context, request):
    return {'next_url': persona_add(context, request)}


# For catching & handling stashed addition requests.
@view_config(
    route_name='controls.persona.add',
    permission='auth.persona',
    request_method='POST',
    xhr=False)
def persona_add_noxhr(context, request):
    return HTTPSeeOther(location=persona_add(context, request))


@view_config(
    route_name='controls.persona.remove',
    permission='auth.persona',
    request_method='POST',
    renderer='account/controls/persona.mako')
def persona_remove(context, request):
    user = request.user
    form = RemovePersonaForm(request, request.POST)
    form.addrs.query = model.session.query(model.IdentityEmail).with_parent(user)

    if not form.validate():
        return {'form': form}

    for target in form.addrs.data:
        user.identity_emails.remove(target)
        request.session.flash(
            u"Removed Persona identity email address: {0}"
            .format(target.email), level=u'success')

    return HTTPSeeOther(location=request.route_url('controls.persona'))


@view_config(
    route_name='controls.openid',
    permission='auth.openid',
    request_method='GET',
    renderer='account/controls/openid.mako')
def openid(context, request):
    user = request.user
    add_openid_form = AddOpenIDForm(request)
    remove_openid_form = RemoveOpenIDForm(request)
    remove_openid_form.openids.query = model.session.query(model.IdentityURL).with_parent(user)

    return dict(
        add_openid_form=add_openid_form,
        remove_openid_form=remove_openid_form,
    )


@view_config(
    route_name='controls.openid.add',
    permission='auth.openid',
    request_method='POST',
    renderer='account/controls/openid.mako')
def openid_add(context, request):
    user = request.user
    form = AddOpenIDForm(request, request.POST)
    remove_form = RemoveOpenIDForm(request)
    remove_form.openids.query = model.session.query(model.IdentityURL).with_parent(user)

    ret = dict(
        add_openid_form=form,
        remove_openid_form=remove_form,
    )

    # Add an OpenID identity URL
    if not form.validate():
        return ret

    try:
        return HTTPSeeOther(location=openid_begin(
            identifier=form.new_openid.data,
            return_url=request.route_url('controls.openid.add_finish'),
            request=request,
            sreg=False,
        ))
    except OpenIDError as exc:
        form.new_openid.errors.append(exc.args[0])
        return ret


@view_config(
    route_name='controls.openid.add_finish',
    permission='auth.openid',
    request_method='GET',
    renderer='account/controls/openid.mako')
def openid_add_finish(context, request):
    user = request.user
    # XXX we should put the attempted openid in here
    form = AddOpenIDForm(request)
    remove_form = RemoveOpenIDForm(request)
    remove_form.openids.query = model.session.query(model.IdentityURL).with_parent(user)

    ret = dict(
        add_openid_form=form,
        remove_openid_form=remove_form,
    )

    # Process a returning OpenID check
    form.validate()  # Ensure new_openid.errors is an appendable list
    try:
        identity_url, identity_webfinger, auth_time, sreg_res = openid_end(request.path_url, request)
    except OpenIDError as exc:
        form.new_openid.errors.append(exc.args[0])
        return ret

    # Allow an OpenID identity to be registered to only one user.
    existing_url = model.session.query(model.IdentityURL) \
        .filter_by(url=identity_url) \
        .first()
    if existing_url:
        if existing_url.user_id == user.id:
            form.new_openid.errors.append(u'You can already authenticate with that OpenID identity.')
        else:
            form.new_openid.errors.append(u'That OpenID identity is already in use by another account.')
        return ret

    openid = model.IdentityURL(url=identity_url)
    user.identity_urls.append(openid)
    request.session.flash(
        u"Added a new identity: {0}".format(identity_url),
        level=u'success', icon=u'user--plus')

    return HTTPSeeOther(location=request.route_url('controls.openid'))


@view_config(
    route_name='controls.openid.remove',
    permission='auth.openid',
    request_method='POST',
    renderer='account/controls/openid.mako')
def openid_remove(context, request):
    user = request.user
    form = RemoveOpenIDForm(request, request.POST)
    form.openids.query = model.session.query(model.IdentityURL).with_parent(user)

    ret = dict(
        remove_openid_form=form,
        add_openid_form=AddOpenIDForm(request),
    )

    # Delete one or more OpenID identity URLs
    if not form.validate():
        return ret  # XXX uhh

    for target in form.openids.data:
        request.session.flash(
            u"Removed OpenID identifier: {0}".format(target.url),
            level=u'success')
        user.identity_urls.remove(target)
    return HTTPSeeOther(location=request.route_url('controls.openid'))

@view_config(
    route_name='controls.auth',
    permission='auth.method',
    request_method='GET',
    renderer='account/controls/authentication.mako')
def authentication(context, request):
    form = AuthenticationForm(request, obj=request.user)

    # Trim options that will be denied
    if (not request.user.cert_auth in ('required', 'sensitive_required') and
            not 'trusted:cert' in effective_principals(request)):
        form.cert_auth.choices = form.cert_auth.choices[:2]

    return {'form': form}

@view_config(
    route_name='controls.auth',
    permission='auth.method',
    request_method='POST',
    renderer='account/controls/authentication.mako')
def authentication_commit(context, request):
    form = AuthenticationForm(request, request.POST, request.user)

    if form.validate():
        form.populate_obj(request.user)
        request.session.flash(u'Authentication options updated.', level=u'success')
        return HTTPSeeOther(location=request.path_url)

    return {'form': form}
