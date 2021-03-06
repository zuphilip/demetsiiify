import logging
from itertools import chain

from flask import current_app, url_for
from iiif_prezi.factory import ManifestFactory


METAMAP = {
    'title': {'en': 'Title', 'de': 'Titel'},
    'language': {'en': 'Language', 'de': 'Sprache'},
    'genre': {'en': 'Genre', 'de': 'Genre'},
    'creator': {'en': 'Creator', 'de': 'Urheber'},
    'other_persons': {'en': 'Other Persons', 'de': 'Andere Personen'},
    'publisher': {'en': 'Publisher', 'de': 'Veröffentlicht von'},
    'pub_place': {'en': 'Publication Place', 'de': 'Publikationsort'},
    'pub_date': {'en': 'Publication Date', 'de': 'Erscheinungsdatum'}
}


LICENSE_MAP = {
    'pdm': 'http://creativecommons.org/licenses/publicdomain/',
    'cc0': 'https://creativecommons.org/publicdomain/zero/1.0/',
    'cc-by': 'http://creativecommons.org/licenses/by/4.0',
    'cc-by-sa': 'http://creativecommons.org/licenses/by-sa/4.0',
    'cc-by-nd': 'http://creativecommons.org/licenses/by-nd/4.0',
    'cc-by-nc': 'http://creativecommons.org/licenses/by-nd/4.0',
    'cc-by-nc-sa': 'http://creativecommons.org/licenses/by-nc-sa/4.0',
    'cc-by-nc-nd': 'http://creativecommons.org/licenses/by-nc-nd/4.0'}


logger = logging.getLogger(__name__)


def make_label(mets_meta):
    label = mets_meta['title'][0]
    if mets_meta.get('creator'):
        label = "{creator}: {label}".format(
            creator="/".join(mets_meta['creator']),
            label=label)
    if mets_meta.get('pub_place') and mets_meta.get('pub_date'):
        label = "{label} ({pub_place}, {pub_date})".format(
            label=label, pub_place=mets_meta['pub_place'],
            pub_date=mets_meta['pub_date'])
    elif mets_meta.get('pub_date'):
        label = "{label} ({pub_date})".format(
            label=label, pub_date=mets_meta['pub_date'])
    elif mets_meta.get('pub_place'):
        label = "{label} ({pub_place})".format(
            label=label, pub_place=mets_meta['pub_place'])
    return label


def make_info_data(identifier, sizes):
    max_width, max_height = max(sizes)
    return {
        '@context': 'http://iiif.io/api/image/2/context.json',
        '@id': '{}://{}/iiif/image/{}'.format(
            current_app.config['PREFERRED_URL_SCHEME'],
            current_app.config['SERVER_NAME'], identifier),
        'protocol': 'http://iiif.io/api/image',
        'profile': ['http://iiif.io/api/image/2/level0.json'],
        'width': max_width,
        'height': max_height,
        'sizes': [{'width': w, 'height': h} for w, h in sizes]}


def make_metadata(mets_meta):
    metadata = [{'label': METAMAP[k],
                 'value': v} for k, v in mets_meta.items() if k in METAMAP]
    metadata.extend({'label': label, 'value': value}
                    for label, value in mets_meta.items()
                    if 'Identifier' in label)
    return metadata


def _get_canvases(toc_entry, phys_to_canvas):
    canvases = []
    for phys_id in toc_entry.phys_ids:
        if phys_id not in phys_to_canvas:
            logger.warn('Could not find a matching canvas for {}'
                        .format(phys_id))
        else:
            canvases.append(phys_to_canvas[phys_id])
    if toc_entry.children:
        canvases.extend(chain.from_iterable(
            _get_canvases(child, phys_to_canvas)
            for child in toc_entry.children))
    return canvases


def _add_toc_ranges(manifest, toc_entries, phys_to_canvas, idx=0):
    for entry in toc_entries:
        if entry.label:
            range = manifest.range(ident='r{}'.format(idx), label=entry.label)
            for canvas in _get_canvases(entry, phys_to_canvas):
                range.add_canvas(canvas)
            idx += 1
        idx = _add_toc_ranges(manifest, entry.children, phys_to_canvas, idx)
    return idx


def make_manifest(ident, mets_doc, physical_map, thumbs_map):
    manifest_factory = ManifestFactory()

    manifest_ident = '{}://{}/iiif/{}/manifest'.format(
        current_app.config['PREFERRED_URL_SCHEME'],
        current_app.config['SERVER_NAME'], ident)
    manifest_factory.set_base_prezi_uri('{}://{}/iiif/{}'.format(
        current_app.config['PREFERRED_URL_SCHEME'],
        current_app.config['SERVER_NAME'], ident))
    manifest_factory.set_base_image_uri('{}://{}/iiif/image'.format(
        current_app.config['PREFERRED_URL_SCHEME'],
        current_app.config['SERVER_NAME']))
    manifest_factory.set_iiif_image_info('2.0', 0)

    manifest = manifest_factory.manifest(ident=manifest_ident,
                                         label=make_label(mets_doc.metadata))
    for meta in make_metadata(mets_doc.metadata):
        manifest.set_metadata(meta)
    manifest.description = mets_doc.metadata.get('description') or ''
    manifest.seeAlso = mets_doc.metadata.get('see_also') or ''
    manifest.related = mets_doc.metadata.get('related') or ''
    manifest.attribution = mets_doc.metadata.get('attribution') or ''
    manifest.logo = mets_doc.metadata.get('logo', '')
    manifest.license = LICENSE_MAP.get(mets_doc.metadata.get('license'), '')

    phys_to_canvas = {}
    seq = manifest.sequence(ident='default')
    for idx, (phys_id, (image_id, label, (width, height))) in enumerate(
            physical_map.items(), start=1):
        page_id = 'p{}'.format(idx)
        canvas = seq.canvas(ident=page_id, label=label or '?')
        anno = canvas.annotation(ident=page_id)
        img = anno.image(image_id, iiif=True)
        img.set_hw(height, width)
        canvas.width = img.width
        canvas.height = img.height
        thumb_width, thumb_height = thumbs_map[image_id]
        canvas.thumbnail = url_for(
            'iiif.get_image', image_id=image_id, region='full',
            size="{},{}".format(thumb_width, thumb_height),
            rotation='0', quality='default', format='jpg',
            _external=True, _scheme=current_app.config['PREFERRED_URL_SCHEME'])
        phys_to_canvas[phys_id] = canvas.id
    _add_toc_ranges(manifest, mets_doc.toc_entries, phys_to_canvas)
    return manifest.toJSON(top=True)


def make_manifest_collection(pagination, subcollections, label, collection_id,
                             page_num=None):
    if page_num is not None:
        page_id = 'p{}'.format(page_num)
    else:
        page_id = 'top'
    collection = {
        "@context": "http://iiif.io/api/presentation/2/context.json",
        "@id": url_for('iiif.get_collection', collection_id=collection_id,
                       page_id=page_id, _external=True),
        "@type": "sc:Collection",
        "total": pagination.total,
        "label": label,
    }
    if collection_id != 'index':
        collection['within'] = url_for(
            'iiif.get_collection', collection_id='index', page_id='top',
            _external=True)
    if page_id == 'top':
        collection.update({
            "first": url_for(
                'iiif.get_collection', collection_id=collection_id,
                page_id='p1', _external=True),
            "last": url_for(
                'iiif.get_collection', collection_id=collection_id,
                page_id='p{}'.format(pagination.pages), _external=True)
        })
    else:
        collection.update({
            'within': url_for(
                'iiif.get_collection', collection_id=collection_id,
                page_id='top', _external=True),
            'startIndex': (pagination.page-1) * pagination.per_page,
            'manifests': [{
                '@id': url_for('iiif.get_manifest', manif_id=m.id,
                               _external=True),
                '@type': 'sc:Manifest',
                'label': m.label,
                'attribution': m.manifest['attribution'],
                'logo': m.manifest['logo'],
                'thumbnail': m.manifest.get(
                    'thumbnail',
                    m.manifest['sequences'][0]['canvases'][0]['thumbnail'])
            } for m in pagination.items]
        })
        if page_num == 1 and subcollections:
            collection['collections'] = []
            for coll in subcollections:
                if not coll.manifests.count():
                    continue
                manifests_pagination = coll.manifests.paginate(
                    page=None, per_page=current_app.config['ITEMS_PER_PAGE'])
                iiif_coll = make_manifest_collection(
                    manifests_pagination, None, coll.label, coll.id, None)
                collection['collections'].append(iiif_coll)
        if pagination.has_next:
            collection['next'] = url_for(
                'iiif.get_collection', collection_id=collection_id,
                page_id='p{}'.format(pagination.next_num), _external=True)
        if pagination.has_prev:
            collection['prev'] = url_for(
                'iiif.get_collection', collection_id=collection_id,
                page_id='p{}'.format(pagination.prev_num), _external=True)
    return collection


def make_annotation_list(pagination, request_url, request_args):
    out = {
        '@context': 'http://iiif.io/api/presentation/2/context.json',
        '@id': request_url,
        '@type': 'sc:AnnotationList',
        'within': {
            '@type': 'sc:Layer',
            'total': pagination.total,
            'first': url_for('iiif.search_annotations', p=1, _external=True,
                             **{k: v for k, v in request_args.items()
                                if k != 'p'}),
            'last': url_for('iiif.search_annotations', p=pagination.pages,
                            _external=True,
                            **{k: v for k, v in request_args.items()
                               if k != 'p'}),
            'ignored': [k for k in request_args
                        if k not in ('q', 'motivation', 'date', 'user', 'p')]
        },
        'startIndex': (pagination.page-1) * pagination.per_page,
        'resources': [a.annotation for a in pagination.items],
    }
    if pagination.has_next:
        out['next'] = url_for(
            'iiif.search_annotations', p=pagination.next_num,
            _external=True,
            **{k: v for k, v in request_args.items()
                if k != 'p'})
    if pagination.has_prev:
        out['next'] = url_for(
            'iiif.search_annotations', p=pagination.prev_num,
            _external=True,
            **{k: v for k, v in request_args.items()
                if k != 'p'})
    return out
