# Open Date Beta for iPhone

The beta bundle ID is `local.opendate.multiuser`. First-time Google users land on Second You. Connect LinkedIn opens LinkedIn’s consent screen, then imports the first name and available profile photo into that Google user's local profile. Settings also offers a refresh and Google sign-out. Work, education, interests and dating preferences remain user-editable. LinkedIn’s standard `openid profile` permission does not grant career or education history.

## Google

In Google Auth Platform, configure the consent screen and create an **iOS** OAuth client for the beta bundle ID. If the Google app is in testing, add the Google accounts of your testers. Set these user-defined Xcode build settings for both Debug and Release:

- `GOOGLE_IOS_CLIENT_ID` — the public iOS client ID.
- `GOOGLE_REVERSED_CLIENT_ID` — the same ID with its dot-separated components in reverse order.
- `OPEN_DATE_BETA_API` — the HTTPS origin of the separately deployed beta backend.

## LinkedIn and beta server

Deploy the `vexo/` backend from this branch to a separate beta service. Register a LinkedIn developer application, enable **Sign In with LinkedIn using OpenID Connect**, and register the exact HTTPS callback URL `https://YOUR-BETA-HOST/api/beta/linkedin/callback`.

Set `GOOGLE_IOS_CLIENT_ID`, `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`, and `LINKEDIN_REDIRECT_URI` on the server. The redirect URI is the registered HTTPS callback. Keep the LinkedIn secret on the server. Configure hosting/access logs to omit callback query strings. The server verifies the Google ID token, exchanges LinkedIn's authorization code and reads the authorized userinfo response. Provider access tokens are discarded after import. Profile data is stored per Google account on the device.

## Distribution

Register the beta bundle ID in the Apple Developer account and create its App Store Connect record. Archive the configured Release build in Xcode, upload it, and submit it to TestFlight external beta review before sharing the invitation link.
