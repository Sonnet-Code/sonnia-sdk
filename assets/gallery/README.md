# Image gallery

Every `.png`, `.jpg` or `.jpeg` file you put directly in this folder is an image Sonnia can show on her screen with the `show_image` action, using the file name without its extension as the `image_id`.

For example, `floor-map.png` is shown by asking for the id `floor-map`.

## Tips for adding images

- PNG and JPEG only. The avatar client cannot decode WebP, so a `.webp` file here is ignored (otherwise Sonnia would say she is showing an image that never appears on screen). Convert it to PNG first.
- File names in `kebab-case`, without spaces or accents (for example `opening-hours.png`, not `Opening Hours.png`).
- Recommended maximum width: about 1920 px. Bigger images only add weight and loading time without looking any better on screen.
- One file per id: if both `floor-map.png` and `floor-map.jpg` exist, only one of them is used, so avoid duplicates with the same name.
- Never put photos of real visitors here. This folder is for content prepared in advance, not a place to keep camera snapshots: camera snapshots are never stored.

## Empty by default

The folder ships without images. Add the ones that make sense for your kiosk or event. With an empty gallery, Sonnia shows no images at all.

You do not need to restart Sonnia when you add or remove images:

- The orchestrator rescans this folder every `GALLERY_WATCH_SECONDS` (5 s by default) and, at the next quiet moment in the conversation, tells the open session what was added or removed with a silent `[Gallery]` note. She does not say it aloud: she shows the images when they fit the conversation. New sessions get the full list in their instructions.
- Images uploaded from the local control panel ("Add image") are stored in `GALLERY_UPLOAD_DIR` (default `cache/gallery`) with ids starting with `upload-`, not in this folder.
