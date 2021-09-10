from django.http import HttpResponse
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt
from decouple import config

import os
import io
import json
import zipfile
import tempfile
import shapefile
from github import Github
from urllib.request import urlopen
from urllib.parse import quote_plus


def get_timehash():
    from hashlib import blake2b
    import time
    k = str(time.time()).encode('utf-8')
    h = blake2b(key=k, digest_size=8)
    return h.hexdigest()

@csrf_exempt
def api_contribute(request):
    print('received')
    data = request.POST
    print(data)
    print(request.FILES)

    # check that agreed
    if not data['agree_to_terms'] == 'agree':
        raise Exception('Contribution requires that the user agrees to the terms, indicated by \
                        the "agree_to_terms" flag set to "agree", but instead received: {}'.format(data['agree_to_terms']))

    # create meta.txt expected by gb PR
    meta_file = create_meta_file(data)
    print('meta', meta_file)

    # standardize the given zip/shapefile to a new shapefile
    fileobj = request.FILES['file']
    archive = zipfile.ZipFile(fileobj)
    for name in archive.namelist():
        if data['path'].endswith(name):
            break
    filename,ext = os.path.splitext(name)
    shp = archive.open(filename+'.shp')
    shx = archive.open(filename+'.shx')
    dbf = archive.open(filename+'.dbf')
    reader = shapefile.Reader(shp=shp, shx=shx, dbf=dbf)
    standardized_shapefile = standardize_uploaded_shapefile(reader,
                                                            level=data['level'],
                                                            name_field=data['name_field'],
                                                            iso=data['iso'],
                                                            iso_field=data['iso_field'])
    print('shapefile', standardized_shapefile, len(standardized_shapefile), standardized_shapefile.fields)

    # load the image file
    try:
        screenshot_fileobj = request.FILES['license_screenshot']
    except:
        screenshot_fileobj = None

    # lastly pack these into a zipfile
    zip_path = tempfile.mktemp()
    submit_archive = zipfile.ZipFile(zip_path, mode='w')
    
    # add meta file
    meta_path = meta_file.name
    submit_archive.writestr('meta.txt', open(meta_path, mode='rb').read())

    # add shapefile
    shp_path = standardized_shapefile.shp.name
    shx_path = standardized_shapefile.shx.name
    dbf_path = standardized_shapefile.dbf.name
    shapefile_name = '{}_{}'.format(data['iso'], data['level'])
    submit_archive.writestr('{}.shp'.format(shapefile_name), open(shp_path, mode='rb').read())
    submit_archive.writestr('{}.shx'.format(shapefile_name), open(shx_path, mode='rb').read())
    submit_archive.writestr('{}.dbf'.format(shapefile_name), open(dbf_path, mode='rb').read())

    # add prj file
    # for now just assume the file is wgs84
    wgs84_wkt = 'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["Degree",0.017453292519943295]'
    submit_archive.writestr('{}.prj'.format(shapefile_name), wgs84_wkt.encode('utf8'))

    # add license screenshot
    if screenshot_fileobj:
        _,ext = os.path.splitext(screenshot_fileobj.name)
        submit_archive.writestr('license{}'.format(ext), screenshot_fileobj.read())

    # close
    submit_archive.close()
    print('zipped files', submit_archive)

    # submit to github
    release_type = 'gbOpen'
    branch = 'gbContribute-{}-{}_{}-{}'.format(release_type, data['iso'], data['level'], get_timehash())
    submit_title = '{}_{} {}'.format(data['iso'], data['level'], release_type)
    submit_body = '''Boundary data for **{iso}-{level}** submitted through the geoBoundaries contribution form. 

**Name**: {name}.
**Affiliation**: {affil}.
**Contact**: {email}.
**Notes about these data**: {notes}
'''.format(iso=data['iso'],
           level=data['level'],
           name=data['contributor_name'],
           affil=data['contributor_affiliation'],
           email=data['contributor_email'],
           notes=data['notes'])
    zip_path_dst = 'sourceData/{}/{}_{}.zip'.format(release_type, data['iso'], data['level'])
    files = {zip_path:zip_path_dst}

    pull_url = submit_to_github(branch, submit_title, submit_body, files=files)
    
    return redirect(pull_url)

def create_meta_file(data):
    writer = open(tempfile.mktemp(), mode='w', encoding='utf8')

    lines = []
    line = 'Boundary Representative of Year: {}'.format(data['year'])
    lines.append(line)
    line = 'ISO-3166-1: {}'.format(data['iso'])
    lines.append(line)
    line = 'Boundary Type: {}'.format(data['level'])
    lines.append(line)
    line = 'Canonical Boundary Name: {}'.format(data.get('type',''))
    lines.append(line)
    i = 1
    for src in data['source'].split(';'):
        line = 'Source {}: {}'.format(i, src)
        lines.append(line)
        i += 1
    line = 'Release Type: {}'.format(data.get('release_type','gbOpen')) # defaults to gbOpen
    lines.append(line)
    line = 'License: {}'.format(data.get('license',''))
    lines.append(line)
    line = 'License Notes: {}'.format(data.get('license_details',''))
    lines.append(line)
    line = 'License Source: {}'.format(data.get('license_url',''))
    lines.append(line)
    line = 'Link to Source Data: {}'.format(data.get('source_url',''))
    lines.append(line)
    line = 'Other Notes: {}'.format(data.get('notes',''))
    lines.append(line)

    content = '\n'.join(lines)
    writer.write(content)
    
    writer.close()
    return writer

def standardize_uploaded_shapefile(reader, level, name_field, iso=None, iso_field=None):
    # create writer
    writer = shapefile.Writer(tempfile.mktemp())
    # required fields
    writer.field('Name', 'C')
    writer.field('Level', 'C')
    if level in ['ADM0','ADM1']:
        writer.field('ISO_Code', 'C')
    # add from reader
    for shaperec in reader:
        rec = shaperec.record
        attr = {'Name':rec[name_field],
               'Level':level,
               }
        if level == 'ADM0':
            # country ISO code
            attr['ISO_Code'] = iso
        elif level == 'ADM1':
            # ADM1 ISO code
            if iso_field:
                attr['ISO_Code'] = rec[iso_field]
            else:
                attr['ISO_Code'] = ''
        writer.record(**attr)
        writer.shape(shaperec.shape)
    # close up
    writer.close()
    return writer

def submit_to_github(branchname, title, body, files):
    # init
    g = Github(config('GITHUB_TOKEN'))
    upstream = g.get_repo('wmgeolab/geoBoundaries') # upstream
    upstream_branch = 'main'
    # get or create the fork
    try:
        # get existing fork
        fork = g.get_user().get_repo('geoBoundaries')
    except:
        # fork doesn't already exist, eg if the geoBoundaryBot's fork has been deleted/cleaned up
        fork = g.get_user().create_fork(upstream)
    # create new branch based on upstream
    fork.create_git_ref(ref='refs/heads/' + branchname, 
                        sha=upstream.get_git_ref(ref='heads/' + upstream_branch).object.sha)
    # commit files to new branch
    for src,dst in files.items():
        message = 'Add {}'.format(dst)
        content = open(src, mode='rb').read()
        try:
            fork.create_file(dst, message, content, branch=branchname)
        except:
            # get sha of existing file by inspecting parent folder's git tree.
            # get_contents() is easier but downloads the entire file and fails
            # for larger filesizes.
            dst_folder = os.path.dirname(dst)
            tree_url = 'https://api.github.com/repos/geoBoundaryBot/geoBoundaries/git/trees/{}:{}'.format(branchname, quote_plus(dst_folder))
            print('parent tree url', tree_url)
            tree = json.loads(urlopen(tree_url).read())
            # loop files in tree until file is found
            for member in tree['tree']:
                if dst.endswith(member['path']):
                    existing_sha = member['sha']
                    break
            fork.update_file(dst, message, content, sha=existing_sha, branch=branchname)
    # make pull request
    pull = upstream.create_pull(title, body, base=upstream_branch, head='geoBoundaryBot:'+branchname)
    
    # return the url
    pull_url = 'https://github.com/wmgeolab/geoBoundaries/pull/{}'.format(pull.number)
    return pull_url

    



