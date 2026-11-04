# DeviceList

Rows of devices: an icon tile, the name and IP, and a value with a mini bar.

**Use**
- "Top devices" on Home and "Top talkers" on Live. Each row is a link to the device page with `row-hover` on hover and `r-md` corners.
- `.tile` is a 36px `surface-3` square (11px radius) holding the device-type icon in `text-2`. On a device page the tile grows to 72px with an accent icon.
- Name in `type-strong-row`, truncating with an ellipsis; IP in mono `text-3`.
- The value is right-aligned and tabular, with a 72px accent `.mini` bar scaled to the top device. Live talkers swap the bar for a mini sparkline and show the rate in Sora ("38.2 Mbps").

**Consumer provides**: name, IP, device type icon, value and the maximum for scaling.
