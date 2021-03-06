from copy import deepcopy
from datetime import datetime
import random
import re
import unicodedata

from webob.multidict import MultiDict
from wtforms import fields, form, widgets, ValidationError
from wtforms.widgets import HTMLString, html_params
from wtforms.ext.sqlalchemy.fields import QuerySelectMultipleField
import pytz

from floof import model


class FloofForm(form.Form):
    """Extends form.Form by attaching a request attribute to itself on
    instantiation and by automatically updating the supplied formdata with any
    post parameters in request.stash"""

    def __init__(self, request, formdata=None, obj=None, prefix='', **kwargs):
        self.request = request

        if request.stash:
            if formdata is None:
                formdata = MultiDict()
            else:
                formdata = deepcopy(formdata)

            if request.stash['post']:
                formdata.update(request.stash['post'])

        super(FloofForm, self).__init__(formdata=formdata, obj=obj,
                                        prefix=prefix, **kwargs)


class KeygenWidget(widgets.Input):
    def __call__(self, field, **kwargs):
        kwargs.setdefault('id', field.id)
        return HTMLString(u'<keygen {0} />'.format(html_params(
                name=field.name,
                challenge=field.challenge,
                keytype=field.keytype,
                **kwargs
                )))

class PassthroughListWidget(widgets.ListWidget):
    """Just like a ListWidget, but passes rendering kwargs to its children."""
    def __call__(self, field, **kwargs):
        html = [u'<%s>' % (self.html_tag)]
        for subfield in field:
            if self.prefix_label:
                html.append(u'<li>%s: %s</li>' % (subfield.label, subfield(**kwargs)))
            else:
                html.append(u'<li>%s %s</li>' % (subfield(**kwargs), subfield.label))
        html.append(u'</%s>' % self.html_tag)
        return HTMLString(u''.join(html))

class IDNAField(fields.TextField):
    """Field for internationalised domain names."""
    def process_formdata(self, valuelist):
        if valuelist:
            self.data = valuelist[0].encode('idna')
        else:
            self.data = ''

    def _value(self):
        if self.data:
            return self.data.decode('idna')
        else:
            return u''

class KeygenField(fields.TextField):
    widget = KeygenWidget()

    def __init__(self, label='', validators=None, keytype='rsa', **kwargs):
        super(KeygenField, self).__init__(label, validators, **kwargs)
        self.keytype = keytype
        # For SPKAC certificate generation.  AFAIK it does not need to be
        # a cryptographically strong radom string, just unique.
        self.challenge = random.getrandbits(128)

# borrowed from spline
class MultiCheckboxField(fields.SelectMultipleField):
    """ A multiple-select, except displays a list of checkboxes.

    Iterating the field will produce subfields, allowing custom rendering of
    the enclosed checkbox fields.
    """
    widget = PassthroughListWidget(prefix_label=False)
    option_widget = widgets.CheckboxInput()

class QueryMultiCheckboxField(QuerySelectMultipleField):
    """`MultiCheckboxField` for SQLAlchemy queries."""
    widget = PassthroughListWidget(prefix_label=False)
    option_widget = widgets.CheckboxInput()


class MultiTagField(fields.TextField):

    def _value(self):
        if self.raw_data:
            return self.raw_data[0]
        elif self.data:
            return u' '.join(sorted(self.data))
        return u''

    _tag_re = re.compile(r'^[a-z0-9\s]*$')
    def process_formdata(self, valuelist):
        if not valuelist:
            self.data = []
            return

        value = valuelist[0]
        if not self._tag_re.match(value):
            raise ValueError("Tags must be lowercase and alphanumeric")

        if value:
            self.data = [x for x in value.strip().split()]
        else:
            self.data = []

def timezone_choices():
    """Helper that generates a list of timezones sorted by ascending UTC
    offset.

    The timezones are represented as tuple pairs of timezone name and a
    string representation of the current UTC offset.
    """
    # TODO: Perfect for caching; the list is unlikely to change more than hourly.
    tzs = []
    now = datetime.utcnow().replace(tzinfo=pytz.utc)
    for tz_name in pytz.common_timezones:
        localnow = now.astimezone(pytz.timezone(tz_name))

        # The real seconds help us sort the TZ list
        offset = localnow.utcoffset()
        offset_real_secs = offset.seconds + offset.days * 24 * 60**2

        offset_txt = localnow.strftime(
                '(UTC %z) [%a %H:%M] {0}').format(tz_name)
        tzs.append((offset_real_secs, tz_name, offset_txt))

    tzs.sort()
    return [tz[1:] for tz in tzs]

def coerce_timezone(value):
    if value is None or \
            value == pytz.utc or \
            isinstance(value, (pytz.tzfile.DstTzInfo, pytz.tzfile.StaticTzInfo)):
        return value
    else:
        try:
            return pytz.timezone(value)
        except (ValueError, pytz.UnknownTimeZoneError):
            # ValueError is recognised by SelectField.process_formdata()
            raise ValueError(u'Not a timezone')

class TimezoneField(fields.SelectField):
    """A simple select field that handles pytz to Olson TZ name conversions.
    """
    def __init__(self, label=None, validators=None, **kwargs):
        super(TimezoneField, self).__init__(label, validators,
                coerce=coerce_timezone, choices=timezone_choices(),
                default='UTC', **kwargs)

    def pre_validate(self, form):
        for v, _ in self.choices:
            if self.data and self.data.zone == v:
                break
        else:
            raise ValueError(self.gettext(u'Not a valid choice'))

class DisplayNameField(fields.TextField):
    # TODO should i be a validator...
    _max_length = model.User.__table__.c.display_name.type.length

    def pre_validate(self, form):
        self.data = self.data.strip()

        if len(self.data) > self._max_length:
            raise ValidationError(
                '{0} characters maximum.'.format(self._max_length))

        for char in self.data:
            # Allow printable ASCII
            # XXX Is there a better way than checking ord(char)?
            if 32 <= ord(char) <= 126:
                continue

            # Disallow combining characters regardless of category
            if unicodedata.combining(char):
                raise ValidationError('No combining characters.')

            # Allow anything non-ASCII categorized as a letter
            if unicodedata.category(char).startswith('L'):
                continue

            raise ValidationError(u'Invalid character: {0}'.format(char))
