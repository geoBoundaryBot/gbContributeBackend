# gbContributeBackend
 Django backend which performs GitHub PR on receiving geoBoundaries contributor POST data

## Requirements for the Heroku app

In the Heroku dashboard:

1. Add python buildpack
2. Add heroku-postgresql addon
3. Add config vars
   - GITHUB_TOKEN (see geoBoundaryBot access tokens)
   - SECRET_KEY (this can be anything and is used by django to encrypt data)
