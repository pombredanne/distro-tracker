# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""Views for the :mod:`distro_tracker.core` app."""
from __future__ import unicode_literals
import importlib
from django.conf import settings
from django.db.models import Q
from django.shortcuts import render, redirect
from django.shortcuts import get_object_or_404
from django.http import Http404
from django.utils.decorators import method_decorator
from django.views.generic import View
from django.views.generic.edit import FormView
from django.views.generic.edit import UpdateView
from django.views.generic.detail import DetailView
from django.views.generic import DeleteView
from django.views.generic import ListView
from django.views.generic import TemplateView
from django.views.decorators.cache import cache_control
from django.core.mail import send_mail
from django.core.exceptions import PermissionDenied
from django.core.urlresolvers import reverse, reverse_lazy
from django.utils.http import urlquote
from distro_tracker.core.models import get_web_package
from distro_tracker.core.forms import CreateTeamForm
from distro_tracker.core.forms import AddTeamMemberForm
from distro_tracker.core.utils import render_to_json_response
from distro_tracker.core.models import SourcePackageName, PackageName
from distro_tracker.core.models import PseudoPackageName, BinaryPackageName
from distro_tracker.core.models import ActionItem
from distro_tracker.core.models import News, NewsRenderer
from distro_tracker.core.models import Keyword
from distro_tracker.core.models import Team
from distro_tracker.core.models import TeamMembership
from distro_tracker.core.models import MembershipConfirmation
from distro_tracker.core.panels import get_panels_for_package
from distro_tracker.accounts.views import LoginRequiredMixin
from distro_tracker.accounts.models import UserEmail
from distro_tracker.core.utils import get_or_none
from distro_tracker.core.utils import distro_tracker_render_to_string


def package_page(request, package_name):
    """
    Renders the package page.
    """
    package = get_web_package(package_name)
    if not package:
        raise Http404
    if package.get_absolute_url() not in (urlquote(request.path), request.path):
        return redirect(package)

    is_subscribed = False
    if request.user.is_authenticated():
        # Check if the user is subscribed to the package
        is_subscribed = request.user.is_subscribed_to(package)

    return render(request, 'core/package.html', {
        'package': package,
        'panels': get_panels_for_package(package, request),
        'is_subscribed': is_subscribed,
    })


def package_page_redirect(request, package_name):
    """
    Catch-all view which tries to redirect the user to a package page
    """
    return redirect('dtracker-package-page', package_name=package_name)


def legacy_package_url_redirect(request, package_hash, package_name):
    """
    Redirects access to URLs in the form of the "old" PTS package URLs to the
    new package URLs.

    .. note::
       The "old" package URL is: /<hash>/<package_name>.html
    """
    return redirect('dtracker-package-page', package_name=package_name,
                    permanent=True)


class PackageSearchView(View):
    """
    A view which responds to package search queries.
    """
    def get(self, request):
        if 'package_name' not in self.request.GET:
            raise Http404
        package_name = self.request.GET.get('package_name').lower()

        package = get_web_package(package_name)
        if package is not None:
            return redirect(package)
        else:
            return render(request, 'core/package_search.html', {
                'package_name': package_name
            })


class OpenSearchDescription(View):
    """
    Return the open search description XML document allowing
    browsers to launch searches on the website.
    """

    def get(self, request):
        return render(request, 'core/opensearch-description.xml', {
            'search_uri': request.build_absolute_uri(
                reverse('dtracker-package-search')),
            'autocomplete_uri': request.build_absolute_uri(
                reverse('dtracker-api-package-autocomplete')),
            'favicon_uri': request.build_absolute_uri(
                reverse('dtracker-favicon')),
        }, content_type='application/opensearchdescription+xml')


class PackageAutocompleteView(View):
    """
    A view which responds to package auto-complete queries.

    Renders a JSON list of package names matching the given query, meaning
    their name starts with the given query parameter.
    """
    @method_decorator(cache_control(must_revalidate=True, max_age=3600))
    def get(self, request):
        if 'q' not in request.GET:
            raise Http404
        query_string = request.GET['q']
        package_type = request.GET.get('package_type', None)
        MANAGERS = {
            'pseudo': PseudoPackageName.objects,
            'source': SourcePackageName.objects,
            'binary': BinaryPackageName.objects.exclude(source=True),
        }
        # When no package type is given include both pseudo and source packages
        filtered = MANAGERS.get(
            package_type,
            PackageName.objects.filter(Q(source=True) | Q(pseudo=True))
        )
        filtered = filtered.filter(name__icontains=query_string)
        # Extract only the name of the package.
        filtered = filtered.values('name')
        # Limit the number of packages returned from the autocomplete
        AUTOCOMPLETE_ITEMS_LIMIT = 100
        filtered = filtered[:AUTOCOMPLETE_ITEMS_LIMIT]
        return render_to_json_response([query_string,
                                        [package['name']
                                         for package in filtered]])


def news_page(request, news_id):
    """
    Displays a news item's full content.
    """
    news = get_object_or_404(News, pk=news_id)

    renderer_class = \
        NewsRenderer.get_renderer_for_content_type(news.content_type)
    if renderer_class is None:
        renderer_class = \
            NewsRenderer.get_renderer_for_content_type('text/plain')

    renderer = renderer_class(news)
    return render(request, 'core/news.html', {
        'news_renderer': renderer,
        'news': news,
    })


class PackageNews(ListView):
    """
    A view which lists all the news of a package.
    """
    _DEFAULT_NEWS_LIMIT = 30
    NEWS_LIMIT = getattr(
        settings,
        'DISTRO_TRACKER_NEWS_PANEL_LIMIT',
        _DEFAULT_NEWS_LIMIT)

    paginate_by = NEWS_LIMIT
    template_name = 'core/package_news.html'
    context_object_name = 'news'

    def get(self, request, package_name):
        self.package = get_object_or_404(PackageName, name=package_name)
        return super(PackageNews, self).get(request, package_name)

    def get_queryset(self):
        news = self.package.news_set.prefetch_related('signed_by')
        return news.order_by('-datetime_created')

    def get_context_data(self, *args, **kwargs):
        context = super(PackageNews, self).get_context_data(*args, **kwargs)
        context['package'] = self.package
        return context


class ActionItemJsonView(View):
    """
    View renders a :class:`distro_tracker.core.models.ActionItem` in a JSON
    response.
    """
    @method_decorator(cache_control(must_revalidate=True, max_age=3600))
    def get(self, request, item_pk):
        item = get_object_or_404(ActionItem, pk=item_pk)
        return render_to_json_response(item.to_dict())


class ActionItemView(View):
    """
    View renders a :class:`distro_tracker.core.models.ActionItem` in an HTML
    response.
    """
    def get(self, request, item_pk):
        item = get_object_or_404(ActionItem, pk=item_pk)
        return render(request, 'core/action-item.html', {
            'item': item,
        })


def legacy_rss_redirect(request, package_hash, package_name):
    """
    Redirects old package RSS news feed URLs to the new ones.
    """
    return redirect(
        'dtracker-package-rss-news-feed',
        package_name=package_name,
        permanent=True)


class KeywordsView(View):
    def get(self, request):
        return render_to_json_response([
            keyword.name for keyword in Keyword.objects.order_by('name').all()
        ])


class CreateTeamView(LoginRequiredMixin, FormView):
    model = Team
    template_name = 'core/team-create.html'
    form_class = CreateTeamForm

    def form_valid(self, form):
        instance = form.save(commit=False)
        user = self.request.user
        instance.owner = user
        instance.save()
        instance.add_members(user.emails.filter(email=user.main_email))

        return redirect(instance)


class TeamDetailsView(DetailView):
    model = Team
    template_name = 'core/team.html'

    def get_context_data(self, **kwargs):
        context = super(TeamDetailsView, self).get_context_data(**kwargs)
        if self.request.user.is_authenticated():
            context['user_member_of_team'] = self.object.user_is_member(
                self.request.user)

        return context


class DeleteTeamView(DeleteView):
    model = Team
    success_url = reverse_lazy('dtracker-team-deleted')
    template_name = 'core/team-confirm-delete.html'

    def get_object(self, *args, **kwargs):
        """
        Makes sure that the team instance to be deleted is owned by the
        logged in user.
        """
        instance = super(DeleteTeamView, self).get_object(*args, **kwargs)
        if instance.owner != self.request.user:
            raise PermissionDenied
        return instance


class UpdateTeamView(UpdateView):
    model = Team
    form_class = CreateTeamForm
    template_name = 'core/team-update.html'

    def get_object(self, *args, **kwargs):
        """
        Makes sure that the team instance to be updated is owned by the
        logged in user.
        """
        instance = super(UpdateTeamView, self).get_object(*args, **kwargs)
        if instance.owner != self.request.user:
            raise PermissionDenied
        return instance


class AddPackageToTeamView(LoginRequiredMixin, View):
    def post(self, request, slug):
        """
        Adds the package given in the POST parameters to the team.

        If the currently logged in user is not a team member, a
        403 Forbidden response is given.

        Once the package is added, the user is redirected back to the team's
        page.
        """
        team = get_object_or_404(Team, slug=slug)
        if not team.user_is_member(request.user):
            # Only team members are allowed to modify the packages followed by
            # the team.
            raise PermissionDenied

        if 'package' in request.POST:
            package_name = request.POST['package']
            package = get_or_none(PackageName, name=package_name)
            if package:
                team.packages.add(package)

        return redirect(team)


class RemovePackageFromTeamView(LoginRequiredMixin, View):
    template_name = 'core/team-remove-package-confirm.html'

    def get_team(self, slug):
        team = get_object_or_404(Team, slug=slug)
        if not team.user_is_member(self.request.user):
            # Only team members are allowed to modify the packages followed by
            # the team.
            raise PermissionDenied

        return team

    def get(self, request, slug):
        self.request = request
        team = self.get_team(slug)

        if 'package' not in request.GET:
            raise Http404
        package_name = request.GET['package']
        package = get_or_none(PackageName, name=package_name)

        return render(self.request, self.template_name, {
            'package': package,
            'team': team,
        })

    def post(self, request, slug):
        """
        Removes the package given in the POST parameters from the team.

        If the currently logged in user is not a team member, a
        403 Forbidden response is given.

        Once the package is removed, the user is redirected back to the team's
        page.
        """
        self.request = request
        team = self.get_team(slug)

        if 'package' in request.POST:
            package_name = request.POST['package']
            package = get_or_none(PackageName, name=package_name)
            if package:
                team.packages.remove(package)

        return redirect(team)


class JoinTeamView(LoginRequiredMixin, View):
    """
    Lets logged in users join a public team.

    After a user has been added to the team, redirect them back to the
    team page.
    """
    template_name = 'core/team-join-choose-email.html'

    def get(self, request, slug):
        team = get_object_or_404(Team, slug=slug)

        return render(request, self.template_name, {
            'team': team,
        })

    def post(self, request, slug):
        team = get_object_or_404(Team, slug=slug)
        if not team.public:
            # Only public teams can be joined directly by users
            raise PermissionDenied

        if 'email' in request.POST:
            emails = request.POST.getlist('email')
            # Make sure the user owns the emails
            user_emails = [e.email for e in request.user.emails.all()]
            for email in emails:
                if email not in user_emails:
                    raise PermissionDenied
            # Add the given emails to the team
            team.add_members(self.request.user.emails.filter(email__in=emails))

        return redirect(team)


class LeaveTeamView(LoginRequiredMixin, View):
    """
    Lets logged in users leave teams they are a part of.
    """
    def get(self, request, slug):
        team = get_object_or_404(Team, slug=slug)
        return redirect(team)

    def post(self, request, slug):
        team = get_object_or_404(Team, slug=slug)
        if not team.user_is_member(request.user):
            # Leaving a team when you're not already a part of it makes no
            # sense
            raise PermissionDenied

        # Remove all the user's emails from the team
        team.remove_members(
            UserEmail.objects.filter(pk__in=request.user.emails.all()))

        return redirect(team)


class ManageTeamMembers(LoginRequiredMixin, ListView):
    """
    Provides the team owner a method to manually add/remove members of the
    team.
    """
    template_name = 'core/team-manage.html'
    paginate_by = 20
    context_object_name = 'members_list'

    def get_queryset(self):
        return self.team.members.all().order_by('email')

    def get_context_data(self, *args, **kwargs):
        context = super(ManageTeamMembers, self).get_context_data(*args,
                                                                  **kwargs)
        context['team'] = self.team
        context['form'] = AddTeamMemberForm()
        return context

    def get(self, request, slug):
        self.team = get_object_or_404(Team, slug=slug)
        # Make sure only the owner can access this page
        if self.team.owner != request.user:
            raise PermissionDenied
        return super(ManageTeamMembers, self).get(request, slug)


class RemoveTeamMember(LoginRequiredMixin, View):
    def post(self, request, slug):
        self.team = get_object_or_404(Team, slug=slug)
        if self.team.owner != request.user:
            raise PermissionDenied

        if 'email' in request.POST:
            emails = request.POST.getlist('email')
            self.team.remove_members(UserEmail.objects.filter(email__in=emails))

        return redirect('dtracker-team-manage', slug=self.team.slug)


class AddTeamMember(LoginRequiredMixin, View):
    def post(self, request, slug):
        self.team = get_object_or_404(Team, slug=slug)
        if self.team.owner != request.user:
            raise PermissionDenied

        form = AddTeamMemberForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            # Emails that do not exist should be created
            user, _ = UserEmail.objects.get_or_create(email=email)
            # The membership is muted by default until the user confirms it
            membership = self.team.add_members([user], muted=True)[0]
            confirmation = MembershipConfirmation.objects.create_confirmation(
                membership=membership)
            send_mail(
                'Team Membership Confirmation',
                distro_tracker_render_to_string(
                    'core/email-team-membership-confirmation.txt',
                    {
                        'confirmation': confirmation,
                        'team': self.team,
                    }),
                from_email=settings.DISTRO_TRACKER_CONTACT_EMAIL,
                recipient_list=[email])

        return redirect('dtracker-team-manage', slug=self.team.slug)


class ConfirmMembershipView(View):
    template_name = 'core/membership-confirmation.html'

    def get(self, request, confirmation_key):
        confirmation = get_object_or_404(
            MembershipConfirmation, confirmation_key=confirmation_key)
        membership = confirmation.membership
        membership.muted = False
        membership.save()
        # The confirmation is no longer necessary
        confirmation.delete()

        return redirect(membership.team)

        return render(request, self.template_name, {
            'membership': membership,
        })


class TeamListView(ListView):
    queryset = Team.objects.filter(public=True).order_by('name')
    paginate_by = 20
    template_name = 'core/team-list.html'
    context_object_name = 'team_list'


class SetMuteTeamView(LoginRequiredMixin, View):
    """
    The view lets users mute or unmute a team membership or a particular
    package in the membership.
    """
    action = 'mute'

    def post(self, request, slug):
        team = get_object_or_404(Team, slug=slug)
        if 'email' not in request.POST:
            raise Http404
        user = request.user
        try:
            email = user.emails.get(email=request.POST['email'])
        except UserEmail.DoesNotExist:
            raise PermissionDenied

        try:
            membership = team.team_membership_set.get(user_email=email)
        except TeamMembership.DoesNotExist:
            raise Http404

        if self.action == 'mute':
            mute = True
        elif self.action == 'unmute':
            mute = False
        else:
            raise Http404

        if 'package' in request.POST:
            package = get_object_or_404(PackageName,
                                        name=request.POST['package'])
            membership.set_mute_package(package, mute)
        else:
            membership.muted = mute
            membership.save()

        if 'next' in request.POST:
            return redirect(request.POST['next'])
        else:
            return redirect(team)


class SetMembershipKeywords(LoginRequiredMixin, View):
    """
    The view lets users set either default membership keywords or
    package-specific keywords.
    """
    def render_response(self):
        if self.request.is_ajax():
            return render_to_json_response({
                'status': 'ok',
            })
        if 'next' in self.request.POST:
            return redirect(self.request.POST['next'])
        else:
            return redirect(self.team)

    def post(self, request, slug):
        self.request = request
        self.team = get_object_or_404(Team, slug=slug)
        user = request.user
        mandatory_parameters = ('email', 'keyword[]')
        if any(param not in request.POST for param in mandatory_parameters):
            raise Http404
        try:
            email = user.emails.get(email=request.POST['email'])
        except UserEmail.DoesNotExist:
            raise PermissionDenied

        try:
            membership = self.team.team_membership_set.get(user_email=email)
        except TeamMembership.DoesNotExist:
            raise Http404

        keywords = request.POST.getlist('keyword[]')
        if 'package' in request.POST:
            package = get_object_or_404(PackageName,
                                        name=request.POST['package'])
            membership.set_keywords(package, keywords)
        else:
            membership.set_membership_keywords(keywords)

        return self.render_response()


class EditMembershipView(LoginRequiredMixin, ListView):
    template_name = 'core/edit-team-membership.html'
    paginate_by = 20
    context_object_name = 'package_list'

    def get(self, request, slug):
        self.team = get_object_or_404(Team, slug=slug)
        if 'email' not in request.GET:
            raise Http404
        user = request.user
        try:
            email = user.emails.get(email=request.GET['email'])
        except UserEmail.DoesNotExist:
            raise PermissionDenied

        try:
            self.membership = \
                self.team.team_membership_set.get(user_email=email)
        except TeamMembership.DoesNotExist:
            raise Http404

        return super(EditMembershipView, self).get(request, slug)

    def get_queryset(self):
        return self.team.packages.all().order_by('name')

    def get_context_data(self, *args, **kwargs):
        # Annotate the packages with a boolean indicating whether the package
        # is muted by the user and a list of keywords specific for the package
        # membership
        for pkg in self.object_list:
            pkg.is_muted = self.membership.is_muted(pkg)
            pkg.keywords = sorted(
                self.membership.get_keywords(pkg),
                key=lambda x: x.name)
        context = super(EditMembershipView, self).get_context_data(*args,
                                                                   **kwargs)
        context['membership'] = self.membership
        return context


class IndexView(TemplateView):
    template_name = 'core/index.html'

    def get_context_data(self, **kwargs):
        context = super(IndexView, self).get_context_data(**kwargs)
        links = []
        for app in settings.INSTALLED_APPS:
            try:
                urlmodule = importlib.import_module(app + '.tracker_urls')
                if hasattr(urlmodule, 'frontpagelinks'):
                    links += [(reverse(name), text)
                              for name, text in urlmodule.frontpagelinks]
            except ImportError:
                pass
        context['application_links'] = links
        return context
