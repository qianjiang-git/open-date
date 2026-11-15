import SwiftUI
import GoogleSignIn
import AuthenticationServices
import CryptoKit

struct BetaAccount {
    let id: String
    let name: String
    let email: String
    var store: UserDefaults { UserDefaults(suiteName: "beta.google." + id)! }

    init?(_ user: GIDGoogleUser) {
        guard let id = user.userID, !id.isEmpty, let profile = user.profile else { return nil }
        self.id = id
        name = profile.givenName ?? profile.name
        email = profile.email
    }
}

@main struct OpenDateApp: App {
    @State private var account: BetaAccount?
    @State private var busy = false
    @State private var error: String?
    private var configured: Bool {
        guard let id = Bundle.main.object(forInfoDictionaryKey: "GIDClientID") as? String,
              id.hasSuffix(".apps.googleusercontent.com"),
              let types = Bundle.main.object(forInfoDictionaryKey: "CFBundleURLTypes") as? [[String: Any]]
        else { return false }
        return types.contains { ($0["CFBundleURLSchemes"] as? [String])?.contains(id.split(separator: ".").reversed().joined(separator: ".")) == true }
    }

    var body: some Scene {
        WindowGroup {
            Group {
                if let account {
                    OpenDateView(account: account) {
                        GIDSignIn.sharedInstance.signOut()
                        self.account = nil
                    }.defaultAppStorage(account.store).id(account.id)
                } else {
                    VStack(alignment: .leading, spacing: 18) {
                        Text("Open Date").font(.largeTitle.bold())
                        Text("Meet people at your event. Sign in to create your own dating profile.")
                        Button(busy ? "Signing in…" : "Continue with Google") {
                            Task { await signIn() }
                        }.buttonStyle(.borderedProminent).disabled(busy)
                        if let error { Text(error).font(.footnote).foregroundStyle(.secondary) }
                    }.padding(28)
                }
            }.onOpenURL { _ = GIDSignIn.sharedInstance.handle($0) }
                .task {
                    guard configured, GIDSignIn.sharedInstance.hasPreviousSignIn() else { return }
                    busy = true
                    defer { busy = false }
                    if let user = try? await GIDSignIn.sharedInstance.restorePreviousSignIn() {
                        account = BetaAccount(user)
                    }
                }
        }
    }

    @MainActor private func signIn() async {
        guard configured else {
            error = "Google sign-in is awaiting configuration for this beta build."
            return
        }
        guard let scene = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).first(where: { $0.activationState == .foregroundActive }),
              let presenter = scene.keyWindow?.rootViewController else { return }
        busy = true
        error = nil
        defer { busy = false }
        do {
            let result = try await GIDSignIn.sharedInstance.signIn(withPresenting: presenter)
            account = BetaAccount(result.user)
            if account == nil { error = "Google did not return an account profile. Please try again." }
        } catch let failure as NSError {
            if failure.code != GIDSignInError.canceled.rawValue { error = "Google sign-in failed. Please try again." }
        }
    }
}

@MainActor
final class LinkedInConnection: NSObject, ObservableObject, ASWebAuthenticationPresentationContextProviding {
    struct Profile: Decodable { let name: String?; let picture: URL? }
    private struct Authorization: Decodable { let url: URL; let state: String }
    struct Failure: LocalizedError { let errorDescription: String? }
    @Published private(set) var busy = false
    @Published private(set) var message = ""
    private var browser: ASWebAuthenticationSession?
    private var anchor: UIWindow?

    func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        anchor ?? ASPresentationAnchor()
    }

    private func post<T: Decodable>(_ path: String, _ fields: [String: String], subject: String) async throws -> T {
        guard let base = Bundle.main.object(forInfoDictionaryKey: "OpenDateBetaAPI") as? String,
              let url = URL(string: base), url.scheme == "https", url.host != nil else {
            throw Failure(errorDescription: "LinkedIn is awaiting configuration for this beta.")
        }
        guard let user = try await GIDSignIn.sharedInstance.currentUser?.refreshTokensIfNeeded(),
              user.userID == subject, let token = user.idToken?.tokenString else {
            throw Failure(errorDescription: "Sign in with Google again to connect LinkedIn.")
        }
        var req = URLRequest(url: url.appendingPathComponent("api/beta/linkedin/" + path))
        req.httpMethod = "POST"
        req.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONEncoder().encode(fields)
        let (data, response) = try await URLSession.shared.data(for: req)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw Failure(errorDescription: "LinkedIn import is unavailable. Please try again later.")
        }
        return try JSONDecoder().decode(T.self, from: data)
    }

    func importProfile(subject: String, apply: (Profile, Data?) -> Void) async {
        guard !busy else { return }
        busy = true
        message = ""
        defer { busy = false; browser = nil; anchor = nil }
        do {
            let verifier = UUID().uuidString + UUID().uuidString
            let challenge = SHA256.hash(data: Data(verifier.utf8)).map { String(format:"%02x", $0) }.joined()
            let auth: Authorization = try await post("start", ["challenge": challenge], subject: subject)
            guard auth.url.scheme == "https", auth.url.host == "www.linkedin.com" else {
                throw Failure(errorDescription: "Invalid LinkedIn authorization URL.")
            }
            anchor = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first { $0.activationState == .foregroundActive }?.keyWindow
            let callback: URL = try await withCheckedThrowingContinuation { continuation in
                let web = ASWebAuthenticationSession(url: auth.url, callbackURLScheme: "opendatebeta") { url, error in
                    if let url { continuation.resume(returning: url) }
                    else { continuation.resume(throwing: error ?? Failure(errorDescription: "Authorization cancelled.")) }
                }
                browser = web
                web.presentationContextProvider = self
                if !web.start() { continuation.resume(throwing: Failure(errorDescription: "Could not open LinkedIn.")) }
            }
            let items = URLComponents(url: callback, resolvingAgainstBaseURL: false)?.queryItems ?? []
            guard callback.host == "linkedin", items.first(where: { $0.name == "state" })?.value == auth.state,
                  let code = items.first(where: { $0.name == "code" })?.value else {
                throw Failure(errorDescription: "LinkedIn authorization wasn’t completed.")
            }
            let profile: Profile = try await post("finish", ["state": auth.state, "code": code, "verifier": verifier], subject: subject)
            var jpg: Data?
            if let photo = profile.picture, photo.scheme == "https", let host = photo.host,
               host.hasSuffix(".licdn.com") || host == "licdn.com",
               let (data, _) = try? await URLSession.shared.data(from: photo),
               let image = UIImage(data: data),
               let thumb = await image.byPreparingThumbnail(ofSize: CGSize(width:240,height:240)) {
                jpg = thumb.jpegData(compressionQuality: 0.85)
            }
            guard GIDSignIn.sharedInstance.currentUser?.userID == subject else { return }
            guard !(profile.name ?? "").isEmpty || jpg != nil else {
                throw Failure(errorDescription: "LinkedIn returned no profile fields.")
            }
            apply(profile, jpg)
            message = "Second You updated from LinkedIn."
        } catch { message = error.localizedDescription }
    }
}
