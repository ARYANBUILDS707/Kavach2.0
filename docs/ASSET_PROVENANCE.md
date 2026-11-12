# Asset provenance

Third-party binary assets shipped with the frontend, where each came from, and how that was checked. Update this file whenever an asset is added, replaced or removed.

Verified on 11 Nov 2026. The font files were downloaded on 9 Nov 2026.

## Fonts

All three are self-hosted from `frontend/public/fonts/` and declared in `frontend/src/styles/tokens.css`. Each is the Google Fonts **latin subset** in WOFF2 form, which Google builds from the family's TTF in the [google/fonts](https://github.com/google/fonts) repository. Google's subsetting and WOFF2 build pipeline is not public, so the local files can be matched byte for byte against Google's served assets, but not against the upstream TTFs.

### How each item was checked

1. **Local hash.** `shasum -a 256` of the file in `frontend/public/fonts/`.
2. **Served asset.** The exact `fonts.gstatic.com` URL returned by the Google Fonts CSS API request below was downloaded again on the verification date and hashed. A matching SHA-256 means the local file is that asset, byte for byte. The same CSS request, made again on the verification date, still returns these URLs for the latin subset.
3. **Internal metadata.** The WOFF2 `name`, `head`, `fvar` and `maxp` tables, read with a scratch script that uses only Node's built-in Brotli; no font tooling was installed.
4. **Upstream chain.** Each family's `METADATA.pb` in google/fonts, read at a pinned commit, names the upstream repository and source commit. The version string inside the served file was compared with the version string of the google/fonts TTF at that commit. The upstream commit was confirmed to exist with the GitHub API.
5. **Licence.** The local `OFL-*.txt` was hashed and compared with `ofl/<family>/OFL.txt` in google/fonts at the same pinned commit.

CSS API request that produced the URLs:

```
https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400..800&family=Instrument+Sans:wght@400..700&family=JetBrains+Mono:wght@500;700&display=swap
```

### Bricolage Grotesque

| Item | Evidence |
|---|---|
| Local file | `frontend/public/fonts/bricolage-grotesque-latin.woff2` (76,868 bytes) |
| SHA-256 | `85f55a58a31e61a2e19e8bb25fed503181bf2a6b4cab76c589992cfaac377447` |
| Served asset (byte-identical) | `https://fonts.gstatic.com/s/bricolagegrotesque/v9/3y9K6as8bTXq_nANBjzKo3IeZx8z6up5BeSl9D4dj_x9PpZBMlGIInHWVyNJ.woff2` (Google Fonts family version `v9`) |
| Internal metadata | Family `Bricolage Grotesque 96pt ExtraBold`, the default-instance name that google/fonts also lists as `full_name`; subfamily `Regular`; PostScript `BricolageGrotesque96ptExtraBold-Regular`; version `Version 1.001;gftools[0.9.33.dev8+g029e19f]`; `head` revision 1.001; axes `opsz 12..96`, `wght 200..800`; 268 glyphs |
| google/fonts | `ofl/bricolagegrotesque/BricolageGrotesque[opsz,wdth,wght].ttf` at commit `6ce172f74aa355ea43eb964fa4a91570a4d3064d`: same version string. That TTF also has a `wdth 75..100` axis, which the served subset omits. |
| Upstream source | `https://github.com/ateliertriay/bricolage`, commit `84745e5b96261ae5f8c6c856e262fe78d1d6efdd` (2023-07-19), file `fonts/variable/BricolageGrotesque[opsz,wdth,wght].ttf`, per `METADATA.pb` |
| Upstream release | None. The repository has no tags or releases, so the commit is the version reference. |
| Copyright | `Copyright 2022 The Bricolage Grotesque Project Authors (https://github.com/ateliertriay/bricolage)`, embedded in the font and in the licence |
| Licence | SIL Open Font License 1.1. `frontend/public/fonts/OFL-bricolagegrotesque.txt`, SHA-256 `4b5a7d8f37f5602621c8a8d7358a6a2e71317e6c231c661e15aef0275d3e07ba`, identical to google/fonts `ofl/bricolagegrotesque/OFL.txt` at `6ce172f7…` |

### Instrument Sans

| Item | Evidence |
|---|---|
| Local file | `frontend/public/fonts/instrument-sans-latin.woff2` (29,904 bytes) |
| SHA-256 | `6219bc4bfdfc5d9b2201dcdf046218b122a758f932e25ed5f168f929b7ca2311` |
| Served asset (byte-identical) | `https://fonts.gstatic.com/s/instrumentsans/v4/pxiTypc9vsFDm051Uf6KVwgkfoSxQ0GsQv8ToedPibnr0SZe1ZuWi3g.woff2` (Google Fonts family version `v4`) |
| Internal metadata | Family `Instrument Sans`; subfamily `Regular`; PostScript `InstrumentSans-Regular`; version `Version 1.000;gftools[0.9.28]`; `head` revision 1.000; axis `wght 400..700`; 244 glyphs |
| google/fonts | `ofl/instrumentsans/InstrumentSans[wdth,wght].ttf` at commit `0b58fb370093f9a9f4ff785d94405710b79de67c`: same version string. That TTF also has a `wdth 75..100` axis, which the served subset omits. |
| Upstream source | `https://github.com/Instrument/instrument-sans`, commit `7fa22308a3d0c94ee2b3cd537a1196b65db34a3e` (2023-06-14), file `fonts/variable/InstrumentSans[wdth,wght].ttf`, per `METADATA.pb` |
| Upstream release | None. The repository has no tags or releases, so the commit is the version reference. |
| Copyright | `Copyright 2022 The Instrument Sans Project Authors (https://github.com/Instrument/instrument-sans)`, embedded in the font and in the licence |
| Licence | SIL Open Font License 1.1. `frontend/public/fonts/OFL-instrumentsans.txt`, SHA-256 `9e27a72ed30eb49a08678f6a5d6ed98ec7ba5368f541637ee0683ec9134ef966`, identical to google/fonts `ofl/instrumentsans/OFL.txt` at `0b58fb37…` |

### JetBrains Mono

| Item | Evidence |
|---|---|
| Local file | `frontend/public/fonts/jetbrains-mono-latin.woff2` (31,340 bytes) |
| SHA-256 | `2c32b9b3ee358c119e210f6f5195f9bd34894d78a785ff2e95d60e718e400af4` |
| Served asset (byte-identical) | `https://fonts.gstatic.com/s/jetbrainsmono/v24/tDbv2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKwBNntkaToggR7BYRbKPxDcwgknk-4.woff2` (Google Fonts family version `v24`; the CSS API serves this one file for both weights 500 and 700) |
| Internal metadata | Family `JetBrains Mono`; subfamily `Regular`; PostScript `JetBrainsMono-Regular`; version `Version 2.211`; `head` revision 2.211; axis `wght 400..800`; 394 glyphs |
| google/fonts | `ofl/jetbrainsmono/JetBrainsMono[wght].ttf` at commit `6e4b84c976cadb3c49a40fd9a1c203e4f7fcf2da`: same version string (`Version 2.211`). That TTF's axis is `wght 100..800`; the served subset is limited to 400..800. |
| Upstream source | `https://github.com/JetBrains/JetBrainsMono`, commit `19371302b95d218af43299bce79ddbddd0bc364d` (2025-01-31), file `fonts/variable/JetBrainsMono[wght].ttf`, per `METADATA.pb` |
| Upstream release | **Unresolved.** No `v2.211` tag or release exists. The nearest tags are `v2.210` and `v2.221`, and the latest release is `v2.304`. Version 2.211 is the internal version of the file at the commit above, which is the version reference. |
| Copyright | `Copyright 2020 The JetBrains Mono Project Authors (https://github.com/JetBrains/JetBrainsMono)`, embedded in the font and in the licence |
| Licence | SIL Open Font License 1.1. `frontend/public/fonts/OFL-jetbrainsmono.txt`, SHA-256 `b2fe5e8987594e9ffd1d2ca52a2f5d73eb8335243893c5d6254b5ad69269591d`, identical to google/fonts `ofl/jetbrainsmono/OFL.txt` at `6e4b84c9…` |

### Unresolved or limited evidence

- **Served files vs upstream TTFs.** Each served WOFF2 is a subset that Google derived from the google/fonts TTF, so it cannot be compared with the upstream binary byte for byte. The link rests on matching version strings, copyright lines and axis ranges, plus the source commit recorded in `METADATA.pb`. Google does not publish which google/fonts commit produced each served version (`v9`, `v4`, `v24`). The pinned google/fonts commits above are the latest commits touching each family's directory on the verification date. Their version strings match the served files, but they are not proven to be the exact build input.
- **JetBrains Mono release tag.** No tagged release corresponds to version 2.211; see the table above.
- **Glyph coverage.** The latin subset does not include Devanagari. The landing page's `कवच` (marked `lang="sa"`) renders in a system fallback font.

### Licence obligations (SIL OFL 1.1)

- Each font ships with its licence file in the same directory, and the build copies both into `dist/fonts/`.
- The fonts are not sold on their own.
- The subsets are Google's unmodified files, so no Reserved Font Name issue arises from renaming or modification.
- If a font file is ever modified locally, for example re-subset, its name must be reviewed against the licence's Reserved Font Name terms and this file updated.

### Updating a font

1. Request the CSS API URL for the family.
2. Download the latin `woff2` it names.
3. Record the new gstatic URL, SHA-256 and internal version here.
4. Re-read `METADATA.pb` and `OFL.txt` at a pinned google/fonts commit.
5. Replace the licence file if it changed.
