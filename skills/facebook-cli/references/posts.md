# Facebook Posts

## Browsing a Profile's Timeline

To view recent posts for a profile, use `timeline fetch`:

```bash
facebook-cli timeline fetch --profile-id <profile-id>
```

## Reading Comments or Reactions

```bash
facebook-cli post comments read --post-id <post-id>
facebook-cli post reactions read --post-id <post-id>
```

## Operating Rules

1. When presenting normalized feed or timeline posts, include `post_caption` and `url` when present. A feed caption that matches `header_text`, or a caption derived from `media_summary`, is descriptive provider text rather than the author's quoted words. Do not fabricate links or text when these fields are absent.
2. Include the owner's name only when the user isn't asking about a specific person (e.g., browsing a feed). Omit it when the context already makes the author obvious.
3. When summarizing what someone has been up to, ground every claim in a specific post. Do not fabricate or infer activities that are not evidenced by an actual post.
4. Use normalized `media_summary`, `media_ocr`, or `video_transcript` fields when present to provide media context.
5. Media fields are pre-computed and may not be available for all posts. Never claim a post contains specific media content unless one of those fields confirms it.
