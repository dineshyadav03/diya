# Third-party notices

## Libraries.dev (Jakub Antalik) — MIT

Diya's message box used to be ported from the demo chat-input mock in
[Jakubantalik/Libraries.dev](https://github.com/Jakubantalik/Libraries.dev), with six of that
author's npm packages around it. The interface was redesigned (`docs/UI_DESIGN.md`): the mock's
rules, markup and fit-to-width scaling, and the packages (`voice-glow`, `border-beam`, `liquid-gooey`,
`metal-fx`, `thinking-orbs`, `img-fx`), are gone. What remains from that source:

- `frontend/public/icons/mic-16.svg` (from `sites/home/public/assets/icons/`), used by the
  Hold to talk button.
- `frontend/public/icons/arrow-up-16.svg`, on the Send button: committed together with the composer
  and built the same way, but its source was not written down at the time, so it is treated as part
  of the same MIT-licensed set.

```
MIT License

Copyright (c) 2026 Jakub Antalik

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
