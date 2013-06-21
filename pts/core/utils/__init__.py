# Copyright 2013 The Debian Package Tracking System Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/ptsauthors
#
# This file is part of the Package Tracking System. It is subject to the
# license terms in the LICENSE file found in the top-level directory of
# this distribution and at http://deb.li/ptslicense. No part of the Package
# Tracking System, including this file, may be copied, modified, propagated, or
# distributed except according to the terms contained in the LICENSE file.

from __future__ import unicode_literals
from django.conf import settings
from django.template.loader import render_to_string
from django.contrib.sites.models import Site

from .email_messages import extract_email_address_from_header
from .email_messages import get_decoded_message_payload


def get_or_none(model, **kwargs):
    """
    Gets a Django Model object from the database or returns None if it
    does not exist.
    """
    try:
        return model.objects.get(**kwargs)
    except model.DoesNotExist:
        return None


def pts_render_to_string(template_name, context=None):
    """
    A custom function to render a template to a string which injects extra
    PTS-specific information to the context, such as the name of the derivative.

    This function is necessary since Django's TEMPLATE_CONTEXT_PROCESSORS only
    work when using a RequestContext, wheras this function can be called
    independently from any HTTP request.
    """
    if context is None:
        context = {}
    extra_context = {
        'PTS_VENDOR_NAME': settings.PTS_VENDOR_NAME,
        'PTS_CONTACT_EMAIL': settings.PTS_CONTACT_EMAIL,
        'PTS_CONTROL_EMAIL': settings.PTS_CONTROL_EMAIL,
        'PTS_SITE_DOMAIN': Site.objects.get_current(),
    }
    context.update(extra_context)

    return render_to_string(template_name, context)
