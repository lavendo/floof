<%def name="thumbnail(artwork)">
## Spits out..  a thumbnail of this artwork.  It's an <li>, so this should be
## called inside a <ul>.
<li class="thumbnail">
    <a href="${h.art_url(artwork)}">
        <img src="${config['filestore'].url(artwork.hash + '.thumbnail')}" alt="">
    </a>
    <div class="thumbnail-meta">
        ${artwork.title or 'Untitled'}&nbsp;&nbsp;<img src="${media_icon(artwork.media_type)}">
    </div>
</li>
</%def>

<%def name="media_icon(type)">
## Spits out a URL, should be called from an img tag.
## Add an entry for each media type here
%if type=="image":
    icons/image.png
%elif type=="music":
    icons/music-beam.png
%else:
    icons/question.png
%endif
</%def>