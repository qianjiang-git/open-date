import Foundation

/// Client for the Vexo Signal server (https://vexo-match.onrender.com).
/// Joins by name, keeps itself "online" by polling, lists who else is online, and sends
/// accept / reject answers. The Mac running the Vexo bracelet client ("kgen") turns an
/// answer into a green (accept) or red (reject) light on the wrist band.
final class VexoSignal: ObservableObject {
    static let server = URL(string: "https://vexo-match.onrender.com")!
    /// Member whose bracelet lights up when a person has no matching server member.
    static let braceletOwner = "kgen"

    struct Member: Identifiable, Decodable, Equatable { let id: String; let name: String }
    struct Incoming: Equatable { let seq: Int; let answer: String; let from: String }

    @Published private(set) var members: [Member] = []
    @Published private(set) var incoming: Incoming?
    @Published private(set) var status = "Not connected"

    private var name = ""
    private var token: String?
    private var loop: Task<Void, Never>?

    @MainActor func start(name: String) {
        stop()
        self.name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !self.name.isEmpty else { return }
        loop = Task { @MainActor [weak self] in
            while !Task.isCancelled {
                await self?.tick()
                try? await Task.sleep(nanoseconds: 1_500_000_000)
            }
        }
    }

    @MainActor func stop() {
        loop?.cancel(); loop = nil
        token = nil; members = []; incoming = nil; status = "Not connected"
    }

    /// Answer a person: goes to the member with the same name, else to the bracelet owner.
    @MainActor func send(_ answer: String, to person: String) {
        guard token != nil else { return }
        let target = members.first { $0.name.caseInsensitiveCompare(person) == .orderedSame }?.name ?? Self.braceletOwner
        Task.detached { _ = try? await self.request("POST", "/api/signal", ["to": target, "answer": answer]) }
    }

    @MainActor private func tick() async {
        do {
            if token == nil { try await join() }
            if let data = try await request("GET", "/api/signal", nil),
               let json = try JSONSerialization.jsonObject(with: data) as? [String: Any],
               let s = json["signal"] as? [String: Any], let seq = s["seq"] as? Int,
               let answer = s["answer"] as? String, let from = s["from"] as? String, incoming?.seq != seq {
                incoming = Incoming(seq: seq, answer: answer, from: from)
            }
            if let data = try await request("GET", "/api/signal/members", nil) {
                struct List: Decodable { let members: [Member] }
                members = try JSONDecoder().decode(List.self, from: data).members.filter { $0.name != name }
            }
            status = "Connected as \(name)"
        } catch VexoError.unauthorized {
            token = nil                       // server restarted or lease expired: join again next tick
        } catch {
            status = "Server unreachable, retrying"
        }
    }

    @MainActor private func join() async throws {
        var candidate = name
        for attempt in 0..<3 {
            do {
                guard let data = try await request("POST", "/api/signal/join", ["name": candidate], auth: false),
                      let json = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let t = json["token"] as? String else { throw VexoError.badResponse }
                token = t; name = candidate; return
            } catch VexoError.conflict where attempt < 2 {
                candidate = "\(name)-\(Int.random(in: 10...99))"      // name already online elsewhere
            }
        }
        throw VexoError.conflict
    }

    private enum VexoError: Error { case unauthorized, conflict, badResponse }

    private func request(_ method: String, _ path: String, _ body: [String: String]?, auth: Bool = true) async throws -> Data? {
        var req = URLRequest(url: Self.server.appendingPathComponent(path), timeoutInterval: 60)   // first call can wake a sleeping host
        req.httpMethod = method
        if let body { req.httpBody = try JSONSerialization.data(withJSONObject: body); req.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        if auth, let token { req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        let (data, resp) = try await URLSession.shared.data(for: req)
        switch (resp as? HTTPURLResponse)?.statusCode ?? 0 {
        case 200..<300: return data
        case 401: throw VexoError.unauthorized
        case 409: throw VexoError.conflict
        default: throw VexoError.badResponse
        }
    }
}
