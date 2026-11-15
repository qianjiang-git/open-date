import Foundation
import Combine

@MainActor
final class VexoSignal: ObservableObject {
    static let server = URL(string: "https://vexo-match.onrender.com")!
    static let braceletOwner = "kgen"

    enum Answer: String { case accept, reject }
    struct Member: Decodable { let name: String; let online: Bool? }
    struct Incoming: Decodable { let seq: Int; let answer: String; let from: String }
    private struct Session: Decodable { let token: String }
    private struct Roster: Decodable { let members: [Member] }
    private struct Poll: Decodable { let signal: Incoming? }
    private enum Failure: Error { case http(Int) }

    @Published private(set) var status = "Not connected"
    @Published private(set) var delivery: String?
    private(set) var incoming: Incoming?
    private var pending: [(answer: Answer, person: String)] = []
    private var profile = ""
    private var connectionID = UUID()
    private var token: String?
    private var alias = ""

    func send(_ answer: Answer, to person: String) {
        pending.append((answer, person))
        delivery = "Waiting to send"
    }

    func approveBracelet() async -> String {
        let message: String
        do {
            guard token != nil else { return "Connecting to Vexo. Run Instant matching again in a moment." }
            let roster = try JSONDecoder().decode(Roster.self, from: await request("/api/signal/members"))
            guard roster.members.contains(where: { $0.online != false && $0.name.caseInsensitiveCompare(Self.braceletOwner) == .orderedSame }) else {
                let offline = "Kagen’s receiver is offline. Connect it as kgen, then run Instant matching again."
                delivery = offline
                return offline
            }
            _ = try await request("/api/signal", body: ["to": Self.braceletOwner, "answer": Answer.accept.rawValue])
            message = "Green signal sent to Kagen’s bracelet receiver."
        } catch Failure.http(401) {
            token = nil
            message = "Reconnecting to Vexo. Run Instant matching again in a moment."
        } catch {
            message = "Vexo couldn’t confirm delivery. Run Instant matching again to retry."
        }
        delivery = message
        return message
    }

    func connect(name: String) async {
        let name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        let id = UUID()
        connectionID = id
        if profile != name {
            profile = name; token = nil; incoming = nil; pending.removeAll(); delivery = nil
        }
        guard !name.isEmpty else { status = "Set a profile name to connect"; return }
        defer { if connectionID == id { status = "Not connected" } }
        while !Task.isCancelled && connectionID == id {
            do {
                if token == nil {
                    status = "Connecting…"
                    try await join(name)
                }
                let poll = try await request("/api/signal")
                incoming = try JSONDecoder().decode(Poll.self, from: poll).signal ?? incoming
                let roster = try JSONDecoder().decode(Roster.self, from: await request("/api/signal/members"))
                status = "Connected as " + alias
                while let item = pending.first {
                    let recipient = roster.members.first { $0.online != false && $0.name != alias && $0.name.caseInsensitiveCompare(item.person) == .orderedSame }?.name ?? Self.braceletOwner
                    do {
                        _ = try await request("/api/signal", body: ["to": recipient, "answer": item.answer.rawValue])
                        delivery = "Sent " + item.answer.rawValue + " to " + recipient
                    } catch Failure.http(401) { throw Failure.http(401) }
                    catch {
                        try Task.checkCancellation()
                        delivery = "Delivery unconfirmed for " + recipient
                    }
                    pending.removeFirst()
                }
            } catch Failure.http(401) {
                token = nil; status = "Reconnecting…"
            } catch {
                if Task.isCancelled { break }
                status = "Server unavailable · retrying"
            }
            try? await Task.sleep(for: .seconds(1.5))
        }
    }

    private func join(_ name: String) async throws {
        var candidate = name
        for _ in 0..<3 {
            do {
                let data = try await request("/api/signal/join", body: ["name": candidate])
                token = try JSONDecoder().decode(Session.self, from: data).token
                alias = candidate
                return
            } catch Failure.http(409) {
                candidate = name + "-" + String(Int.random(in: 10...99))
            }
        }
        throw Failure.http(409)
    }

    private func request(_ path: String, body: [String: String]? = nil) async throws -> Data {
        var req = URLRequest(url: Self.server.appendingPathComponent(path), cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 60)
        if let body {
            req.httpMethod = "POST"
            req.httpBody = try JSONEncoder().encode(body)
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        if let token { req.setValue("Bearer " + token, forHTTPHeaderField: "Authorization") }
        let (data, response) = try await URLSession.shared.data(for: req)
        try Task.checkCancellation()
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(code) else { throw Failure.http(code) }
        return data
    }
}
