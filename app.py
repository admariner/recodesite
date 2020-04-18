import os
import datetime
import re
import urllib
from unidecode import unidecode
from werkzeug.utils import secure_filename

from flask import Flask, request, render_template, redirect, Markup, jsonify
from flask.ext.mongoengine import mongoengine

import models
import boto

mongoengine.connect('mydata', host=os.environ.get('MONGOLAB_URI'), retryWrites=False)

app = Flask(__name__)
app.config['CSRF_ENABLED'] = False
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.secret_key = os.environ.get('SECRET_KEY')

AUTH_STR = os.environ.get('AUTH_STR')
ALLOWED_EXTENSIONS = set(['png', 'jpg', 'jpeg', 'gif', 'pde', 'js'])


# ----------------------------------------------------------------- HOME >>>
@app.route("/")
def index():

    artworks = models.Artwork.objects()

    templateData = {
        'artworks': artworks,
    }

    return render_template("index.html", **templateData)


# ---------------------------------------------------------------- SUBMIT >>>
@app.route("/submit/<artwork_slug>", methods=['GET', 'POST'])
def submit(artwork_slug):

    orig = models.Artwork.objects.get(slug=artwork_slug)
    submit_form = models.upload_form(request.form)

    if request.method == "POST":

        translation = models.Translation()
        translation.timestamp = datetime.datetime.now()
        translation.title = request.form.get(
            'title', 'untitled')                               # required
        translation.artist = request.form.get(
            'artist', 'anonymous')                            # required
        translation.artist_email = request.form.get(
            'artist-email', 'none')     # required
        # required, will default to 'direct'
        translation.category = request.form.get('category', 'direct')
        translation.artist_url = request.form.get('artist-url', "none")

        descriptionList = []
        translation.description = request.form.get('description', None)
        if translation.description:
            descriptionList = translation.description.split("\r\n")
        else:
            translation.description = 'No description provided'
        translation.video = Markup(request.form.get('video', 'none'))

        # IMAGE FILE
        photo_upload = request.files['photo-upload']
        if photo_upload and allowed_file(photo_upload.filename):
            now = datetime.datetime.now()
            filename = "p" + \
                now.strftime('%Y%m%d%H%M%s') + \
                secure_filename(photo_upload.filename)
            app.logger.info(os.environ.get(
                'AWS_ACCESS_KEY_ID'), os.environ.get('AWS_SECRET_ACCESS_KEY'))
            s3conn = boto.connect_s3(os.environ.get(
                'AWS_ACCESS_KEY_ID'), os.environ.get('AWS_SECRET_ACCESS_KEY'))
            # bucket name defined in .env
            b = s3conn.get_bucket(os.environ.get('AWS_BUCKET'))
            k = b.new_key(b)
            k.key = filename
            k.set_metadata("Content-Type", photo_upload.mimetype)
            k.set_contents_from_string(photo_upload.stream.read())
            k.make_public()

            if k and k.size > 0:
                translation.photo_link = "https://s3.amazonaws.com/recode-files/" + filename

        else:
            return "Uhoh! There was an error uploading " + photo_upload.filename

        # CODE STRING (required)
        translation.code = "/* \nPart of the ReCode Project (http://recodeproject.com)\n" + "Based on \"" + orig.title + "\" by " + orig.artist + "\n" + "Originally published in \"" + orig.source + "\" " + orig.source_detail + ", " + \
            orig.date + "\nCopyright (c) " + now.strftime('%Y') + " " + translation.artist + " - " + \
            "OSI/MIT license (http://recodeproject/license).\n*/\n\n/* @pjs pauseOnBlur=\"true\"; */\n\n" + \
            request.form.get('code').strip()
        # backup as pde file
        if translation.code:
            now = datetime.datetime.now()
            now = now.strftime('%Y%m%d%H%M%s')
            # now = now.encode('ASCII')
            filename = translation.artist + now + ".pde"
            filename = filename.replace(" ", "")
            s3conn = boto.connect_s3(os.environ.get(
                'AWS_ACCESS_KEY_ID'), os.environ.get('AWS_SECRET_ACCESS_KEY'))
            # bucket name defined in .env
            b = s3conn.get_bucket(os.environ.get('AWS_BUCKET'))
            k = b.new_key(b)
            k.key = filename
            k.set_metadata("Content-Type", 'application/octet-stream')
            k.set_contents_from_string(translation.code)
            k.make_public()
            root = "https://s3.amazonaws.com/recode-files/"
            translation.pde_link = str(root + filename)

        # JS BOOLEAN
        browser_note = "This sketch does not run in the browser."
        if request.form.get('js') == "True":
            translation.js = True
            browser_note = "This sketch is running in the browser."

        translation.artwork_slug = orig.slug
        translation.slug = slugify(translation.artist + "-" + translation.title +
                                   "-" + translation.category + "-" + orig.title + "-" + orig.artist)
        translation.description = translation.description + " " + browser_note
        translation.save()

        orig.hasTranslation = "yes"
        orig.save()

        templateData = {
            'translation': translation,
            'orig': orig,
            'descriptionList': descriptionList
        }

        return redirect("/translation/%s" % translation.slug)

    else:

        templateData = {
            'form': submit_form,
            'orig': orig
        }

        return render_template("submit.html", **templateData)


# ---------------------------------------------------------------- ARTWORK >>>
@app.route("/artwork/<artwork_slug>")
def artwork(artwork_slug):

    NoneString = ""
    artwork = models.Artwork.objects.get(slug=artwork_slug)

    translations = []
    allTranslations = models.Translation.objects()
    for t in allTranslations:
        if t.artwork_slug == artwork_slug:
            translations.append(t)

    if len(translations) == 0:
        NoneString = "(None)"

    templateData = {
        'artwork': artwork,
        'translations': translations,
        'NoneString': NoneString
    }

    return render_template("artwork.html", **templateData)


# ------------------------------------------------------------- TRANSLATION >>>
@app.route("/translation/<trans_slug>")
def translation(trans_slug):

    translation = models.Translation.objects.get(slug=trans_slug)
    orig = models.Artwork.objects.get(slug=translation.artwork_slug)
    descriptionList = translation.description.split("\r\n")

    templateData = {
        'translation': translation,
        'orig': orig,
        'descriptionList': descriptionList
    }

    return render_template("translation.html", **templateData)


# -------------------------------------------------------- ALL TRANSLATIONS >>>
@app.route("/alltranslations")
def alltranslations():

    translations = []

    allTranslations = models.Translation.objects.order_by('-timestamp')
    for t in allTranslations:
        translations.append(t)

    templateData = {
        'translations': translations
    }

    return render_template("alltranslations.html", **templateData)


# -------------------------------------------------------------------- LIST >>>
@app.route("/translationslist", methods=['GET', 'POST'])
def translationslist():

    filter_str = request.form.get('filter')
    app.logger.debug(filter_str)

    artworks = []
    translations = []

    allArtworks = models.Artwork.objects()
    if filter_str == "hasTranslation":
        for a in allArtworks:
            if a.hasTranslation == "yes":
                artworks.append(a)
    elif filter_str == "noTranslation":
        for a in allArtworks:
            if a.hasTranslation == None:
                artworks.append(a)
    elif filter_str == "direct":
        allTranslations = models.Translation.objects()
        for t in allTranslations:
            if t.category == "direct":
                translations.append(t)
    elif filter_str == "experimental":
        allTranslations = models.Translation.objects()
        for t in allTranslations:
            if t.category == "experimental":
                translations.append(t)
    elif filter_str == "artist":
        artworks = sorted(allArtworks, key=lambda k: k[filter_str])
    elif filter_str == "title":
        artworks = sorted(allArtworks, key=lambda k: k[filter_str])
    elif filter_str == "translator":
        allTranslations = models.Translation.objects()
        translations = sorted(allTranslations, key=lambda k: k["artist"])
    elif filter_str == "js":
        allTranslations = models.Translation.objects()
        for t in allTranslations:
            if t.js == True:
                translations.append(t)

    templateData = {
        'artworks': artworks,
        'translations': translations
    }

    return render_template("translationslist.html", **templateData)


# -------------------------------------------------------------- SEARCH >>>
@app.route("/search", methods=['POST'])
def search():

    artworks = []
    translations = []
    allTranslations = models.Translation.objects()

    search_str = request.form.get('keyword')
    app.logger.debug(search_str)
    search_words = search_str.split()
    for word in search_words:
        word.replace(",", "")

        artwork_title = models.Artwork.objects(title__icontains=word)
        if artwork_title is not None:
            for title in artwork_title:
                artworks.append(title)
                for t in allTranslations:
                    if t.artwork_slug == title.slug:
                        translations.append(t)
        artwork_artist = models.Artwork.objects(artist__icontains=word)
        if artwork_artist is not None:
            for artist in artwork_artist:
                artworks.append(artist)
                for t in allTranslations:
                    if t.artwork_slug == artist.slug:
                        translations.append(t)
        artwork_source = models.Artwork.objects(source__icontains=word)
        if artwork_source is not None:
            for source in artwork_source:
                artworks.append(source)
                for t in allTranslations:
                    if t.artwork_slug == source.slug:
                        translations.append(t)
        artwork_date = models.Artwork.objects(date__icontains=word)
        if artwork_date is not None:
            for date in artwork_date:
                artworks.append(date)
                for t in allTranslations:
                    if t.artwork_slug == date.slug:
                        translations.append(t)
        artwork_descr = models.Artwork.objects(description__icontains=word)
        if artwork_descr is not None:
            for descr in artwork_descr:
                artworks.append(descr)
                for t in allTranslations:
                    if t.artwork_slug == descr.slug:
                        translations.append(t)

        translation_title = models.Translation.objects(title__icontains=word)
        if translation_title is not None:
            for title in translation_title:
                translations.append(title)
        translation_artist = models.Translation.objects(artist__icontains=word)
        if translation_artist is not None:
            for artist in translation_artist:
                translations.append(artist)
        translation_orig = models.Translation.objects(
            artwork_slug__icontains=word)
        if translation_orig is not None:
            for orig in translation_orig:
                translations.append(orig)
        translation_descr = models.Translation.objects(
            description__icontains=word)
        if translation_descr is not None:
            for descr in translation_descr:
                translations.append(descr)

    if len(artworks) > 0 or len(translations) > 0:
        error_str = ""
        templateData = {
            'artworks': artworks,
            'translations': translations,
            'error_str': error_str,
            'search_str': search_str
        }
        return render_template("searchresults.html", **templateData)
    else:
        error_str = "No results were returned. If you think this is an error, please send us an email using the mail icon at the top-right of your screen."
        return render_template("searchresults.html", error_str=error_str)


@app.route("/license")
def license():

    return render_template("license.html")


# ---------------------------------------------------------------- DATA >>>
@app.route("/data")
def data():
    # Give title, artist, original work img URL, list of recodes w/author, recode img URLs, runs in-browser flag.
    artworks = []

    all_artworks = models.Artwork.objects()
    for a in all_artworks:
        app.logger.debug(a.title)
        artwork = {
            'title': a.title,
            'artist': a.artist,
            'year': a.date,
            'orig_img_url': "http://recodeproject.com" + a.photo_link,
            'id': str(a.id),
            'static_url': "http://recodeproject.com/artwork/" + a.slug
        }

        if a.hasTranslation == 'yes':
            artwork['recodes'] = []
            all_translations = models.Translation.objects(artwork_slug=a.slug)
            for at in all_translations:
                split = at.photo_link.split("/")
                imglinkrel = split[4]
                recode = {
                    'author': at.artist,
                    'title': at.title,
                    'category': at.category,
                    'recode_img_url': "https://s3.amazonaws.com/recode-files/" + imglinkrel,
                    'js': at.js,
                    'pde_link': at.pde_link,
                    'id': str(at.id),
                    'timestamp': str(a.id.generation_time),
                    'static_url': "http://recodeproject.com/translation/" + at.slug
                }
                artwork['recodes'].append(recode)

        artworks.append(artwork)

    data = {
        'status': 'OK',
        'artworks': artworks
    }

    return jsonify(data)


@app.route("/guide")
def guide():

    return render_template("userguide.html")


@app.route("/survey")
def survey():

    return render_template("survey.html")


@app.route("/featured")
def featured():

    return render_template("featured.html")


# ---------------------------------------------------------------- TEST >>>
@app.route("/testtesttest")
def test():

    # all_translations = models.Translation.objects()

    # for t in all_translations:
    #       if "static" in t.photo_link:
    #               split = t.photo_link.split("/")
    #               t.photo_link = "https://s3.amazonaws.com/recode-files/" + split[4]
    #               t.save
    #               app.logger.debug(t.photo_link)

    return render_template("index.html")
    # allTranslations = models.Translation.objects()
    # for t in allTranslations:
    #       t.update( {$rename : {photo : photo_link }} )

    # return redirect("/")

# ----------------------------------------------------------- 404 HANDLER >>>
@app.errorhandler(404)
def page_not_found(error):
    return render_template('404.html'), 404


def allowed_file(filename):
    return '.' in filename and \
           filename.lower().rsplit('.', 1)[1] in ALLOWED_EXTENSIONS


# via http://flask.pocoo.org/snippets/5/
_punct_re = re.compile(r'[\t !"#$%&\'()*\-/<=>?@\[\\\]^_`{|},.]+')


def slugify(text, delim=u'-'):
    """Generates an ASCII-only slug."""
    result = []
    for word in _punct_re.split(text.lower()):
        result.extend(unidecode(word).split())
    return str(delim.join(result))


# --------------------------------------------------------- SERVER START-UP >>>
if __name__ == "__main__":
    app.debug = True

    # locally PORT 5000, Heroku will assign its own port
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
