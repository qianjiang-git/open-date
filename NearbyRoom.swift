import Foundation
import CoreBluetooth
import Combine

struct DateProfile: Codable, Identifiable, Equatable {
    var id: UUID = UUID()
    var name: String
    var interests: [String]
    var lookingFor: String
    var occupation: String?
    var education: String?
    var personality: String?
    var floorCode: String?
    var symbol: String
    static let cues = ["sparkles", "moon.stars.fill", "sun.max.fill", "leaf.fill"]
    static let choices = ["Design", "Music", "Outdoors", "Food", "Film", "Making things"]
    static let kagen = DateProfile(id: UUID(uuidString: "F56D7367-943D-42F2-9205-27A8BA6F03FD")!, name: "Kagen", interests: ["Photography", "Live music"], lookingFor: "Someone to explore with", occupation: "Architect", education: "B.Arch. in Architecture", personality: "I shoot film on weekends. Pick a neighborhood and I’ll find us a coffee spot.", symbol: "camera")
    static let examples = [
        DateProfile(id: UUID(uuidString:"00000000-0000-4000-A000-000000000001")!, name: "Ari", interests: ["Design", "Music"], lookingFor: "A creative collaborator", occupation: "Graphic designer", education: "BFA in Graphic Design", personality: "I design gig posters and keep a running list of tiny music venues. Ask me about the show I went to last Friday.", symbol: "sparkles"),
        DateProfile(id: UUID(uuidString:"00000000-0000-4000-A000-000000000002")!, name: "Jules", interests: ["Outdoors", "Food"], lookingFor: "An adventure buddy", occupation: "Trail guide", education: "BS in Environmental Science", personality: "My ideal Saturday starts on a coastal trail and ends at a noodle shop neither of us has tried.", symbol: "leaf.fill"),
        DateProfile(id: UUID(uuidString:"00000000-0000-4000-A000-000000000003")!, name: "Remy", interests: ["Music", "Film"], lookingFor: "Someone to explore with", occupation: "Film editor", education: "BA in Film Studies", personality: "I make short films and collect records. Always looking for someone to catch a matinee with.", symbol: "moon.stars.fill")
    ]
    var cue: String { Self.cues.contains(symbol) ? symbol : "sparkles" }
}

struct Encounter: Identifiable {
    let profile: DateProfile
    let strength: Int
    var id: UUID { profile.id }
}

final class NearbyRoom: NSObject, ObservableObject, CBCentralManagerDelegate, CBPeripheralManagerDelegate, CBPeripheralDelegate {
    static let service = CBUUID(string:"EDAB53C2-A1B4-42AA-93CF-604728B550EA")
    private let profileKey = CBUUID(string:"10ED5D69-E6A6-4030-97B9-1DA25996342C")
    @Published private(set) var peers: [Encounter] = []
    @Published private(set) var status = ""
    private var central: CBCentralManager?
    private var host: CBPeripheralManager?
    private var local: DateProfile?
    @Published private(set) var incoming: Set<UUID> = []
    private var pending: Set<UUID> = []
    private let likeKey = CBUUID(string:"10ED5D69-E6A6-4030-97B9-1DA25996342D")
    func like(_ id:UUID) {
        guard let deviceID=profiles.first(where:{$0.value.id == id})?.key, let device=devices[deviceID] else {return}
        pending.insert(id)
        if device.state == .connected { device.discoverServices([Self.service]) }
        else {central?.connect(device)}
    }
    private var devices: [UUID: CBPeripheral] = [:]
    private var profiles: [UUID: DateProfile] = [:]
    private var signals: [UUID: Int] = [:]
    private var seen: [UUID: Date] = [:]
    private var timer: Timer?
    func start(_ profile: DateProfile) {
        stop()
        local = profile
        central = CBCentralManager(delegate: self, queue: .main)
        host = CBPeripheralManager(delegate: self, queue: .main)
        timer = Timer.scheduledTimer(withTimeInterval: 3, repeats: true) { [weak self] _ in self?.refresh() }
    }
    func stop() {
        local = nil
        timer?.invalidate()
        if central?.state == .poweredOn {
            central?.stopScan()
            for device in devices.values { central?.cancelPeripheralConnection(device) }
        }
        if host?.state == .poweredOn { host?.stopAdvertising(); host?.removeAllServices() }
        central?.delegate = nil; host?.delegate = nil
        devices.removeAll(); profiles.removeAll(); signals.removeAll(); seen.removeAll()
        incoming = []; pending = []; central = nil; host = nil; peers = []; status = ""
    }
    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        guard local != nil else { return }
        if central.state == .poweredOn {
            status = "Looking for people nearby"
            central.scanForPeripherals(withServices: [Self.service], options: [CBCentralManagerScanOptionAllowDuplicatesKey:true])
        } else { peers = []; status = "Bluetooth unavailable. Use two Bluetooth-enabled iPhones or try the demo room." }
    }
    func peripheralManagerDidUpdateState(_ peripheral: CBPeripheralManager) {
        guard local != nil, peripheral.state == .poweredOn else { return }
        let service = CBMutableService(type: Self.service, primary: true)
        service.characteristics = [CBMutableCharacteristic(type: profileKey, properties: .read, value: nil, permissions: .readable), CBMutableCharacteristic(type: likeKey, properties: .write, value: nil, permissions: .writeable)]
        peripheral.add(service)
    }
    func peripheralManager(_ peripheral: CBPeripheralManager, didAdd service: CBService, error: Error?) {
        guard local != nil, error == nil else { return }
        peripheral.startAdvertising([CBAdvertisementDataServiceUUIDsKey:[Self.service]])
    }
    func peripheralManager(_ peripheral: CBPeripheralManager, didReceiveRead request: CBATTRequest) {
        guard let local, request.characteristic.uuid == profileKey, let data = try? JSONEncoder().encode(local), request.offset <= data.count else {
            peripheral.respond(to: request, withResult: .unlikelyError); return
        }
        request.value = data.subdata(in: request.offset..<data.count)
        peripheral.respond(to: request, withResult: .success)
    }
    func peripheralManager(_ peripheral: CBPeripheralManager, didReceiveWrite requests: [CBATTRequest]) {
        guard let first=requests.first else {return}
        guard local != nil, requests.count == 1, first.characteristic.uuid == likeKey, let data=first.value, let raw=String(data:data,encoding:.utf8), let sender=UUID(uuidString:raw) else {
            peripheral.respond(to:first,withResult:.requestNotSupported);return
        }
        incoming.insert(sender); peripheral.respond(to:first,withResult:.success)
    }
    func centralManager(_ central: CBCentralManager, didDiscover device: CBPeripheral, advertisementData: [String:Any], rssi RSSI: NSNumber) {
        guard local != nil, RSSI.intValue < 0 else { return }
        let id = device.identifier
        seen[id] = Date(); signals[id] = RSSI.intValue
        if devices[id] == nil {
            devices[id] = device; device.delegate = self
            central.connect(device)
        }
        refresh()
    }
    func centralManager(_ central: CBCentralManager, didConnect device: CBPeripheral) { device.discoverServices([Self.service]) }
    func centralManager(_ central: CBCentralManager, didFailToConnect device: CBPeripheral, error: Error?) { devices.removeValue(forKey:device.identifier) }
    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        for service in peripheral.services ?? [] where service.uuid == Self.service { peripheral.discoverCharacteristics([profileKey,likeKey], for:service) }
    }
    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        if let id=profiles[peripheral.identifier]?.id, pending.contains(id), let local, let field=service.characteristics?.first(where:{$0.uuid==likeKey}) {
            peripheral.writeValue(Data(local.id.uuidString.utf8),for:field,type:.withResponse);return
        }
        if let field = service.characteristics?.first(where:{$0.uuid == profileKey}) { peripheral.readValue(for:field) }
    }
    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        if local != nil, let data = characteristic.value, data.count <= 2048, let profile = try? JSONDecoder().decode(DateProfile.self, from:data), profile.id != local?.id {
            profiles[peripheral.identifier] = profile
        }
        central?.cancelPeripheralConnection(peripheral); refresh()
    }
    func peripheral(_ peripheral: CBPeripheral, didWriteValueFor characteristic: CBCharacteristic, error: Error?) {
        if let id=profiles[peripheral.identifier]?.id, error == nil {pending.remove(id)}
        central?.cancelPeripheralConnection(peripheral)
    }
    private func refresh() {
        guard local != nil else { return }
        for (id,time) in seen where Date().timeIntervalSince(time)>15 {
            if let device = devices.removeValue(forKey:id) { central?.cancelPeripheralConnection(device) }
            seen.removeValue(forKey:id); profiles.removeValue(forKey:id); signals.removeValue(forKey:id)
        }
        peers = profiles.compactMap { id,p in signals[id].map { Encounter(profile:p,strength:$0) } }
    }
}
