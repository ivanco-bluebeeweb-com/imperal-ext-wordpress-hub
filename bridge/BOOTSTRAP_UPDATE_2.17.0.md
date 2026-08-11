# Imperal Bridge 2.17.0 — one-time bootstrap update

This package is the **one-time manual update** that unlocks safe automatic
future updates of the Imperal Bridge from WordPress Hub.

## Package

- Version: **2.17.0**
- ZIP: `bridge/imperal-bridge.zip`
- Published ZIP: <https://raw.githubusercontent.com/ivanco-bluebeeweb-com/imperal-ext-wordpress-hub/main/bridge/imperal-bridge.zip>
- SHA-256: `4acc22614b113fd640b1a0b821666502ac9caad2097890a7e5f2da27b73e6f99`

## One-time installation on each WordPress site

1. Sign in to that site's WordPress administrator area with an administrator
   account.
2. Open **Plugins → Add New Plugin → Upload Plugin**.
3. Upload `imperal-bridge.zip` from this release.
4. If WordPress reports that Imperal Bridge already exists, choose the
   replacement/overwrite option. Keep the plugin active afterwards.
5. Confirm that **Imperal Bridge** reports version **2.17.0** in the installed
   plugins list.

The ZIP contains only:

- `imperal-bridge/imperal-bridge.php`
- `imperal-bridge/README.md`

## What changes afterwards

Version 2.17.0 provides the authenticated endpoint used by WordPress Hub's
`update_imperal_bridge` function. It is deliberately fixed-source:

- callers cannot choose a URL, ZIP, plugin folder, or plugin target;
- the Bridge reads only Imperal's fixed release manifest and ZIP URL;
- it verifies the ZIP SHA-256 before WordPress extracts it;
- it uses WordPress's native `Plugin_Upgrader` and verifies the installed
  version after update.

This does **not** provide a general plugin-upload or arbitrary remote-code
mechanism. Once 2.17.0 is installed on a connected site, future Bridge
releases can be applied by Webbee through `update_imperal_bridge` (16 credits,
standard single-plugin update).
