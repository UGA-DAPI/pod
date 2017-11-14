# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.conf import settings
from elasticsearch import Elasticsearch
from pods.forms import SearchForm
from pods.viewsdir.channel_views import *
from pods.viewsdir.completion_views import *
from pods.viewsdir.favorites_views import *
from pods.viewsdir.owners_views import *
from pods.viewsdir.videos_views import *
from pods.viewsdir.live_views import *
from pods.viewsdir.mediacourses_views import *
from pods.viewsdir.enrichment_views import *
from pods.viewsdir.chapters_views import *
from pods.viewsdir.categories_views import *

import urllib2

USE_PRIVATE_VIDEO = getattr(settings, 'USE_PRIVATE_VIDEO', False)
if USE_PRIVATE_VIDEO:
    from core.models import get_media_guard

DEFAULT_PER_PAGE = 12
VIDEOS = Pod.objects.filter(is_draft=False, encodingpods__gt=0).distinct()
ES_URL = getattr(settings, 'ES_URL', ['http://127.0.0.1:9200/'])

referer = ''

# SEARCH

def search_videos(request):
    es = Elasticsearch(ES_URL)
    aggsAttrs = ['owner_full_name', 'type.title',
                 'disciplines.title', 'tags.name', 'channels.title']

    # SEARCH FORM
    search_word = ""
    start_date = None
    end_date = None
    searchForm = SearchForm(request.GET)
    if searchForm.is_valid():
        search_word = searchForm.cleaned_data['q']
        start_date = searchForm.cleaned_data['start_date']
        end_date = searchForm.cleaned_data['end_date']

    # request parameters
    selected_facets = request.GET.getlist(
        'selected_facets') if request.GET.getlist('selected_facets') else []
    page = request.GET.get('page') if request.GET.get('page') else 0
    size = request.COOKIES.get('perpage') if request.COOKIES.get(
        'perpage') and request.COOKIES.get('perpage').isdigit() else DEFAULT_PER_PAGE
    #page = request.GET.get('page')
    try:
        page = int(page.encode('utf-8'))
    except:
        page = 0
    try:
        size = int(size.encode('utf-8'))
    except:
        size = DEFAULT_PER_PAGE

    search_from = page * size

    # Filter query
    filter_search = {}
    filter_query = ""

    if len(selected_facets) > 0 or start_date or end_date:
        filter_search = {"and": []}
        for facet in selected_facets:
            term = facet.split(":")[0]
            value = facet.split(":")[1]
            filter_search["and"].append({
                "term": {
                    "%s" % term: "%s" % value
                }
            })
        if start_date or end_date:
            filter_date_search = {}
            filter_date_search["range"] = {"date_added": {}}
            if start_date:
                filter_date_search["range"]["date_added"][
                    "gte"] = "%04d-%02d-%02d" % (start_date.year, start_date.month, start_date.day)
            if end_date:
                filter_date_search["range"]["date_added"][
                    "lte"] = "%04d-%02d-%02d" % (end_date.year, end_date.month, end_date.day)

            filter_search["and"].append(filter_date_search)

    # Query
    query = {"match_all": {}}
    if search_word != "":
        query = {
            "multi_match": {
                "query":    "%s" % search_word,
                "fields": ["_id", "title^1.1", "owner^0.9", "owner_full_name^0.9", "description^0.6", "tags.name^1",
                           "contributors^0.6", "chapters.title^0.5", "enrichments.title^0.5", "type.title^0.6", "disciplines.title^0.6", "channels.title^0.6"
                           ]
            }
        }

    # bodysearch
    bodysearch = {
        "from": search_from,
        "size": size,
        "query": {},
        "aggs": {},
        "highlight": {
            "pre_tags": ["<strong>"],
            "post_tags": ["</strong>"],
            "fields": {"title": {}}
        }
    }

    bodysearch["query"] = {
        "function_score": {
            "query": {},
            "functions": [
                {
                    "gauss": {
                        "date_added": {
                            "scale": "10d",
                            "offset": "5d",
                            "decay": 0.5
                        }
                    }
                }
            ]
        }
    }

    if filter_search != {}:
        bodysearch["query"]["function_score"]["query"] = {"filtered": {}}
        bodysearch["query"]["function_score"][
            "query"]["filtered"]["query"] = query
        bodysearch["query"]["function_score"]["query"][
            "filtered"]["filter"] = filter_search
    else:
        bodysearch["query"]["function_score"]["query"] = query

    #bodysearch["query"] = query

    for attr in aggsAttrs:
        bodysearch["aggs"][attr.replace(".", "_")] = {
            "terms": {"field": attr + ".raw", "size": 5, "order": {"_count": "asc"}}}

    # add cursus and main_lang 'cursus', 'main_lang',
    bodysearch["aggs"]['cursus'] = {
        "terms": {"field": "cursus", "size": 5, "order": {"_count": "asc"}}}
    bodysearch["aggs"]['main_lang'] = {
        "terms": {"field": "main_lang", "size": 5, "order": {"_count": "asc"}}}

    if settings.DEBUG:
        print json.dumps(bodysearch, indent=4)

    result = es.search(index="pod", body=bodysearch)

    if settings.DEBUG:
        print json.dumps(result, indent=4)

    remove_selected_facet = ""
    for facet in selected_facets:
        term = facet.split(":")[0]
        value = facet.split(":")[1]
        agg_term = term.replace(".raw", "")
        if result["aggregations"].get(agg_term):
            del result["aggregations"][agg_term]
        else:
            if agg_term == "type.slug":
                del result["aggregations"]["type_title"]
            if agg_term == "tags.slug":
                del result["aggregations"]["tags_name"]
            if agg_term == "disciplines.slug":
                del result["aggregations"]["disciplines_title"]

        # Create link to remove facet
        url_value = value
        if agg_term == "cursus":
            for tab in settings.CURSUS_CODES:
                if tab[0] == value:
                    value = tab[1]
        if agg_term == "main_lang":
            for tab in settings.ALL_LANG_CHOICES:
                if tab[0] == value:
                    value = tab[1]

        url_value = u'%s'.decode('latin1') % url_value
        url_value = url_value.encode('utf-8')
        url_value = urllib2.quote(url_value)
        link = request.get_full_path().replace(
            "&selected_facets=%s:%s" % (term, url_value), "")
        msg_title = (u'Remove selection')
        remove_selected_facet += u'&nbsp;<a href="%s" title="%s"><span class="glyphicon glyphicon-remove" aria-hidden="true"></span>%s</a>&nbsp;' % (
            link, msg_title, value)

    # Pagination mayby better idea ?
    objects = []
    for i in range(0, result["hits"]["total"]):
        objects.append(i)
    paginator = Paginator(objects, size)
    try:
        search_pagination = paginator.page(page + 1)
    except:
        search_pagination = paginator.page(paginator.num_pages)

    return render_to_response("search/search_video.html",
                              {"result": result, "page": page,
                                  "search_pagination": search_pagination, "form": searchForm, "remove_selected_facet": remove_selected_facet},
                              context_instance=RequestContext(request))


# OEMBED

def video_oembed(request):
    format = request.GET.get('format')
    if format and format !="json":
        HttpResponse.status_code = '501'
        return HttpResponse(_(u'You are not authorized to view this resource'))
    url = request.GET.get('url')
    if not(url):
        HttpResponse.status_code = '404'
        return HttpResponse(_(u'The requested address was not found on this server.'))
    is_video = False
    video_position = url.find("/video/")
    is_video_private = False
    video_priv_position = url.find("/video_priv/")
    if video_position>0:
        is_video = True
    if video_priv_position>0:
        is_video_private = True
    if is_video:
        start = url.find('/video/') + 7
        end = url.find('/', start)
        slug = url[int(start):int(end)]
        try:
            id = int(slug[:find(slug, "-")])
        except ValueError:
            raise SuspiciousOperation('Invalid video id')
        video = get_object_or_404(Pod, id=id)
        if video.is_draft:
            HttpResponse.status_code = '401'
            return HttpResponse(_(u'You are not authorized to view this resource'))
        if video.is_restricted:
            HttpResponse.status_code = '401'
            return HttpResponse(_(u'You are not authorized to view this resource'))
    if is_video_private:
        start = url.find('/video_priv/') + 12
        stop1 = url.find('/', start)
        id = int(url[int(start):int(stop1)])
        stop2 = url.find('/', stop1+1)
        slug = url[int(stop1+1):int(stop2)]
        video = get_object_or_404(Pod, id=id)
        hash_id = get_media_guard(video.owner.username, video.id)
        if hash_id != slug:
            HttpResponse.status_code = '401'
            return HttpResponse("nok : key is not valid")

    if video.get_mediatype()[0] == 'audio':
        type = 'rich'
        thumbnail_url =  settings.STATIC_URL  + settings.DEFAULT_IMG
        thumbnail_width = 256
        thumbnail_height = 144
    else :
        type = video.get_mediatype()[0]
        thumbnail_url = video.thumbnail.url
        thumbnail_width = video.thumbnail.width
        thumbnail_height = video.thumbnail.height

    height = 360
    width = 640
    if request.GET.get('maxheight'):
        height = min(360,int(request.GET.get('maxheight')))
    if request.GET.get('maxwidth'):
        width = min(640,int(request.GET.get('maxwidth')))

    if is_video_private:
        code_integration = '<iframe src="//' + request.META.get('HTTP_HOST') + '/video_priv/' + str(id) + '/' + slug + '/' + '?is_iframe=true" width="' + str(width) + '" height="' + str(height) + '" style="padding: 0; margin: 0; border:0" allowfullscreen ></iframe>'
    else:
        code_integration = '<iframe src="//' + request.META.get('HTTP_HOST') + '/video/' + slug + '?is_iframe=true" width="' + str(width) + '" height="' + str(height) + '" style="padding: 0; margin: 0; border:0" allowfullscreen ></iframe>'
    protocole="http://"
    if request.is_secure():
        protocole="https://"
    some_data_to_dump = {
        'version' : "1.0",
        'provider_name' : settings.TITLE_SITE,
        "provider_url" : protocole + request.META.get('HTTP_HOST') + '/',
        "type" : type,
        "title" : video.title,
        "author_url" :  protocole + request.META.get('HTTP_HOST') + "/videos/?owner=" + video.owner.username,
        "author_name" : video.owner.first_name + " " + video.owner.last_name,
        "width" : width,
        "height" : height,
        "html" : code_integration,
        "thumbnail_url" : protocole + request.META.get('HTTP_HOST') + thumbnail_url,
        "thumbnail_width" : thumbnail_width,
        "thumbnail_height"  : thumbnail_height,
    }
    data = json.dumps(some_data_to_dump)
    return HttpResponse(data, content_type='application/json')

def autocomplete(request):
    suggestions = [entry.object.title for entry in res]
    # Make sure you return a JSON object, not a bare list.
    # Otherwise, you could be vulnerable to an XSS attack.
    the_data = json.dumps({})
    return HttpResponse(the_data, content_type='application/json')