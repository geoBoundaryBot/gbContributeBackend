from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from decouple import config

import os
import io
import zipfile
import tempfile
import shapefile
from github import Github


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

    # create meta.txt expected by gb PR
    meta_file = create_meta_file(data)
    print('meta', meta_file)

    # standardize the file to a new shapefile
    print(request.FILES)
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
                                                            iso=data['iso'],
                                                            level=data['level'],
                                                            name_field=data['name_field'])
    print('shapefile', standardized_shapefile, len(standardized_shapefile), standardized_shapefile.fields)

    # lastly pack these into a zipfile
    shapefile_name = '{}_{}'.format(data['iso'], data['level'])

    zip_path = tempfile.mktemp()
    submit_archive = zipfile.ZipFile(zip_path, mode='w')

    meta_path = meta_file.name
    shp_path = standardized_shapefile.shp.name
    shx_path = standardized_shapefile.shx.name
    dbf_path = standardized_shapefile.dbf.name
    
    submit_archive.writestr('meta.txt', open(meta_path, mode='rb').read())
    submit_archive.writestr('{}.shp'.format(shapefile_name), open(shp_path, mode='rb').read())
    submit_archive.writestr('{}.shx'.format(shapefile_name), open(shx_path, mode='rb').read())
    submit_archive.writestr('{}.dbf'.format(shapefile_name), open(dbf_path, mode='rb').read())

    submit_archive.close()
    print('zipped files', submit_archive)

    # submit to github
    release_type = 'gbOpen'
    branch = 'gbContribute-{}-{}_{}-{}'.format(release_type, data['iso'], data['level'], get_timehash())
    submit_title = '{}_{} {}'.format(data['iso'], data['level'], release_type)
    submit_body = '''
Data submitted by {name}, from {affil}.
Contact: {email}.
Notes about these data: {notes}
'''.format(name=data['contributor_name'],
           affil=data['contributor_affiliation'],
           email=data['contributor_email'],
           notes=data['notes'])
    zip_path_dst = 'sourceData/{}/{}_{}.zip'.format(release_type, data['iso'], data['level'])
    files = {zip_path:zip_path_dst}
    submit_to_github(branch, submit_title, submit_body, files=files)
    
    return HttpResponse(status=200)

def create_meta_file(data):
    writer = open(tempfile.mktemp(), mode='w', encoding='utf8')
    
    line = 'Boundary Representative of Year: {}'.format(data['year'])
    writer.writeline(line)
    line = 'ISO-3166-1: {}'.format(data['iso'])
    writer.writeline(line)
    line = 'Boundary Type: {}'.format(data['level'])
    writer.writeline(line)
    line = 'Canonical Boundary Name: {}'.format(data.get('type',''))
    writer.writeline(line)
    i = 1
    for src in data['source'].split(';'):
        line = 'Source {}: {}'.format(i, src)
        writer.writeline(line)
        i += 1
    line = 'Release Type: {}'.format(data.get('release',''))
    writer.writeline(line)
    line = 'License: {}'.format(data.get('license',''))
    writer.writeline(line)
    line = 'License Notes: {}'.format(data.get('license_details',''))
    writer.writeline(line)
    line = 'License Source: {}'.format(data.get('license_url',''))
    writer.writeline(line)
    line = 'Link to Source Data: {}'.format(data.get('source_url',''))
    writer.writeline(line)
    line = 'Other Notes: {}'.format(data.get('notes',''))
    writer.writeline(line)
    
    writer.close()
    return writer

def standardize_uploaded_shapefile(reader, iso, level, name_field):
    # create writer
    writer = shapefile.Writer(tempfile.mktemp())
    # required fields
    writer.field('Name', 'C')
    writer.field('Level', 'C')
    writer.field('ISO_Code', 'C')
    # add from reader
    for shaperec in reader:
        rec = shaperec.record
        attr = {'Name':rec[name_field],
               'Level':level,
               'ISO_Code':iso,
               }
        writer.record(attr)
        writer.shape(shaperec.shape)
    # close up
    writer.close()
    return writer

def submit_to_github(branchname, title, body, files):
    # init
    token = config('GITHUB_TOKEN')
    g = Github(token)
    repo = g.get_user().get_repo('boundaryCompare') # geoBoundaries
    oldname = 'main'
    # create new branch
    newname = branchname
    repo.create_git_ref(ref='refs/heads/' + newname, sha=repo.get_branch(oldname).commit.sha)
    # commit files to new branch
    for src,dst in files.items():
        message = 'Add {}'.format(dst)
        content = open(src, mode='rb').read()
        repo.create_file(dst, message, content, branch=newname)
    # make pull request
    repo.create_pull(title, body, base=oldname, head=newname)

##def test_submit_to_github(*args):
##    token = config('GITHUB_TOKEN')
##    from github import Github
##    g = Github(token)
##    repo = g.get_user().get_repo('boundaryCompare')
##    print(repo)
##    oldname = 'main'
##    oldbranch = repo.get_branch(oldname)
##    # create new branch
##    newname = 'testbranch' # gbContribute-{datetimehash}
##    repo.create_git_ref(ref='refs/heads/' + newname, sha=oldbranch.commit.sha)
##    # test commit new file to new branch
##    path = 'test.txt'
##    message = 'testing'
##    content = 'hello world'
##    repo.create_file(path, message, content, branch=newname)
##    # make pull request
##    title = 'Test PR'
##    body = 'hello world'
##    base = oldname
##    head = newname
##    repo.create_pull(title, body, base, head)
    



