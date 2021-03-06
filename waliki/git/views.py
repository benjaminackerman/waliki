import json
from django.shortcuts import render, get_object_or_404, redirect
from django.utils.translation import ugettext_lazy as _
from django.http import Http404
from django.core.management import call_command
from django.http import HttpResponse
from django.core.urlresolvers import reverse
from django.utils.encoding import smart_text
from django.utils.six import StringIO, text_type
from django.views.decorators.csrf import csrf_exempt
from waliki.models import Page
from waliki.forms import PageForm
from waliki.acl import permission_required
from waliki import settings
from . import Git


@permission_required('view_page')
def history(request, slug):
    page = get_object_or_404(Page, slug=slug)
    if request.method == 'POST':
        new, old = request.POST.getlist('commit')
        return redirect('waliki_diff', slug, old, new)
    history = Git().history(page)
    max_changes = max([(v['insertion'] + v['deletion']) for v in history])
    return render(request, 'waliki/history.html', {'page': page,
                                                   'slug': slug,
                                                   'history': history,
                                                   'max_changes': max_changes})


@permission_required('view_page')
def version(request, slug, version, raw=False):
    page = get_object_or_404(Page, slug=slug)
    content = Git().version(page, version)
    if not content:
        raise Http404
    form = PageForm(instance=page, initial={'message': _('Restored version @%s') % version, 'raw': content},
                    is_hidden=True)

    if raw:
        return HttpResponse(content, content_type='text/plain')

    content = Page.preview(page.markup, content)
    return render(request, 'waliki/version.html', {'page': page,
                                                   'content': content,
                                                   'slug': slug,
                                                   'version': version,
                                                   'form': form})


@permission_required('view_page')
def diff(request, slug, old, new, raw=False):
    page = get_object_or_404(Page, slug=slug)
    if raw:
        content = Git().diff(page, new, old)
        return HttpResponse(content, content_type='text/plain')
    space = smart_text(b'\xc2\xa0', encoding='utf-8')  # non-breaking space character
    tab = space * 4
    old_content = Git().version(page, old).replace('\t', tab).replace(' ', space)
    new_content = Git().version(page, new).replace('\t', tab).replace(' ', space)
    return render(request, 'waliki/diff.html', {'page': page,
                                                'old_content': old_content,
                                                'new_content': new_content,
                                                'slug': slug,
                                                'old_commit': old,
                                                'new_commit': new})


def whatchanged(request, pag=1):
    changes = []
    pag = int(pag or 1)
    skip = (pag - 1) * settings.WALIKI_PAGINATE_BY
    max_count = settings.WALIKI_PAGINATE_BY
    total = int(Git().total_commits())
    for version in Git().whatchanged(skip, max_count):
        for path in version[-1]:
            try:
                page = Page.objects.get(path=path)
            except Page.DoesNotExist:
                continue
            changes.append({'page': page, 'author': version[0],
                            'version': version[2], 'message': version[3],
                            'date': version[4]})

    return render(request, 'waliki/whatchanged.html', {'changes': changes,
                                                       'prev': pag - 1 if pag > 1 else None,
                                                       'next': pag + 1 if (total / settings.WALIKI_PAGINATE_BY) > pag else None})


@csrf_exempt
def webhook_pull(request, remote='origin'):
    if request.method == 'POST':
        try:
            log = Git().pull(remote)
            s = StringIO()
            call_command('sync_waliki', stdout=s)
            s.seek(0)
            r = {'pull': log, 'sync': s.read()}
            status_code = 200
        except Exception as e:
            r = {'error': text_type(e)}
            status_code = 500
        return HttpResponse(json.dumps(r), status=status_code,
                            content_type="application/json")

    return HttpResponse("POST to %s" % reverse("waliki_webhook_pull", args=(remote,)))
