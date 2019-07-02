# coding:utf-8
from __future__ import absolute_import, unicode_literals

import csv
import json
import uuid
import codecs
import chardet
from io import StringIO

from django.db import transaction
from django.contrib import messages
from django.utils.translation import ugettext_lazy as _
from django.views.generic import TemplateView, ListView, View
from django.views.generic.edit import CreateView, DeleteView, FormView, UpdateView
from django.urls import reverse_lazy
from django.views.generic.detail import DetailView
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.core.cache import cache
from django.utils import timezone
from django.shortcuts import redirect
from django.contrib.messages.views import SuccessMessageMixin
from django.forms.formsets import formset_factory

from common.mixins import JSONResponseMixin
from common.utils import get_object_or_none, get_logger
from common.permissions import PermissionsMixin, IsOrgAdmin, IsValidUser
from common.const import (
    create_success_msg, update_success_msg, KEY_CACHE_RESOURCES_ID
)
from .. import forms
from ..models import Asset, AdminUser, SystemUser, Label, Node, Domain


__all__ = [
    'AssetListView', 'AssetCreateView', 'AssetUpdateView', 'AssetUserListView',
    'UserAssetListView', 'AssetBulkUpdateView', 'AssetDetailView',
    'AssetDeleteView',
]
logger = get_logger(__file__)


class AssetListView(PermissionsMixin, TemplateView):
    template_name = 'assets/asset_list.html'
    permission_classes = [IsOrgAdmin]

    def get_context_data(self, **kwargs):
        Node.root()
        context = {
            'app': _('Assets'),
            'action': _('Asset list'),
            'labels': Label.objects.all().order_by('name'),
            'nodes': Node.objects.all().order_by('-key'),
        }
        kwargs.update(context)
        return super().get_context_data(**kwargs)


class AssetUserListView(PermissionsMixin, DetailView):
    model = Asset
    context_object_name = 'asset'
    template_name = 'assets/asset_asset_user_list.html'
    permission_classes = [IsOrgAdmin]

    def get_context_data(self, **kwargs):
        context = {
            'app': _('Assets'),
            'action': _('Asset user list'),
        }
        kwargs.update(context)
        return super().get_context_data(**kwargs)


class UserAssetListView(PermissionsMixin, TemplateView):
    template_name = 'assets/user_asset_list.html'
    permission_classes = [IsValidUser]

    def get_context_data(self, **kwargs):
        context = {
            'action': _('My assets'),
            'labels': Label.objects.all().order_by('name'),
            'system_users': SystemUser.objects.all(),
        }
        kwargs.update(context)
        return super().get_context_data(**kwargs)


class AssetCreateView(PermissionsMixin, SuccessMessageMixin, CreateView):
    model = Asset
    form_class = forms.AssetCreateForm
    template_name = 'assets/asset_create.html'
    success_url = reverse_lazy('assets:asset-list')
    permission_classes = [IsOrgAdmin]

    def get_form(self, form_class=None):
        form = super().get_form(form_class=form_class)
        node_id = self.request.GET.get("node_id")
        if node_id:
            node = get_object_or_none(Node, id=node_id)
        else:
            node = Node.root()
        form["nodes"].initial = node
        return form

    def get_protocol_formset(self):
        ProtocolFormset = formset_factory(forms.ProtocolForm, extra=0, min_num=1, max_num=5)
        if self.request.method == "POST":
            formset = ProtocolFormset(self.request.POST)
        else:
            formset = ProtocolFormset()
        return formset

    def form_valid(self, form):
        formset = self.get_protocol_formset()
        valid = formset.is_valid()
        if not valid:
            return self.form_invalid(form)
        protocols = formset.save()
        instance = super().form_valid(form)
        instance.protocols.set(protocols)
        return instance

    def get_context_data(self, **kwargs):
        formset = self.get_protocol_formset()
        context = {
            'app': _('Assets'),
            'action': _('Create asset'),
            'formset': formset,
        }
        kwargs.update(context)
        return super().get_context_data(**kwargs)

    def get_success_message(self, cleaned_data):
        return create_success_msg % ({"name": cleaned_data["hostname"]})


class AssetBulkUpdateView(PermissionsMixin, ListView):
    model = Asset
    form_class = forms.AssetBulkUpdateForm
    template_name = 'assets/asset_bulk_update.html'
    success_url = reverse_lazy('assets:asset-list')
    success_message = _("Bulk update asset success")
    id_list = None
    form = None
    permission_classes = [IsOrgAdmin]

    def get(self, request, *args, **kwargs):
        spm = request.GET.get('spm', '')
        assets_id = cache.get(KEY_CACHE_RESOURCES_ID.format(spm))
        if kwargs.get('form'):
            self.form = kwargs['form']
        elif assets_id:
            self.form = self.form_class(initial={'assets': assets_id})
        else:
            self.form = self.form_class()
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        form = self.form_class(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, self.success_message)
            return redirect(self.success_url)
        else:
            return self.get(request, form=form, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = {
            'app': _('Assets'),
            'action': _('Bulk update asset'),
            'form': self.form,
            'assets_selected': self.id_list,
        }
        kwargs.update(context)
        return super().get_context_data(**kwargs)


class AssetUpdateView(PermissionsMixin, SuccessMessageMixin, UpdateView):
    model = Asset
    form_class = forms.AssetUpdateForm
    template_name = 'assets/asset_update.html'
    success_url = reverse_lazy('assets:asset-list')
    permission_classes = [IsOrgAdmin]

    def get_protocol_formset(self):
        ProtocolFormset = formset_factory(forms.ProtocolForm, extra=0, min_num=1, max_num=5)
        if self.request.method == "POST":
            formset = ProtocolFormset(self.request.POST)
        else:
            initial_data = [{"name": p.name, "port": p.port} for p in self.object.protocols.all()]
            formset = ProtocolFormset(initial=initial_data)
        return formset

    def get_context_data(self, **kwargs):
        formset = self.get_protocol_formset()
        context = {
            'app': _('Assets'),
            'action': _('Update asset'),
            'formset': formset,
        }
        kwargs.update(context)
        return super().get_context_data(**kwargs)

    def get_success_message(self, cleaned_data):
        return update_success_msg % ({"name": cleaned_data["hostname"]})


class AssetDeleteView(PermissionsMixin, DeleteView):
    model = Asset
    template_name = 'delete_confirm.html'
    success_url = reverse_lazy('assets:asset-list')
    permission_classes = [IsOrgAdmin]


class AssetDetailView(PermissionsMixin, DetailView):
    model = Asset
    context_object_name = 'asset'
    template_name = 'assets/asset_detail.html'
    permission_classes = [IsValidUser]

    def get_context_data(self, **kwargs):
        nodes_remain = Node.objects.exclude(assets=self.object)
        context = {
            'app': _('Assets'),
            'action': _('Asset detail'),
            'nodes_remain': nodes_remain,
        }
        kwargs.update(context)
        return super().get_context_data(**kwargs)
