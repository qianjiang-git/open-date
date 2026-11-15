import SwiftUI
import UserNotifications
import MapKit
import PhotosUI
import CoreLocation

struct OpenDateView: View {
    private let plum = Color(red:0.22, green:0.10, blue:0.17)
    private let rose = Color(red:0.64, green:0.18, blue:0.31)
    @StateObject private var room = NearbyRoom()
    @StateObject private var vexo = VexoSignal()
    @State private var roomOnly = false
    @State private var floorCode = ""
    @State private var building = DemoBuilding.exchange
    @State private var currentRoom = 0
    @State private var demo = true
    @State private var open = true
    @State private var instant = false
    @State private var dismissed: Set<UUID> = []
    @State private var alerted: Set<UUID> = []
    @State private var banner: DateProfile?
    @State private var selected: DateProfile?
    @State private var editing = false
    @State private var detail: DateProfile?
    @State private var likes: Set<UUID> = []
    @State private var liveSaved: [DateProfile] = {
        guard let data=UserDefaults.standard.data(forKey:"openDate.matches") else {return []}
        return (try? JSONDecoder().decode([DateProfile].self,from:data))?.filter { !DateProfile.examples.map(\.id).contains($0.id) } ?? []
    }()
    @State private var demoSaved = [DateProfile.examples[2]]
    @State private var demoProfile = DateProfile(name:"Sam", interests:["Design","Music"], lookingFor:"Someone to explore with", personality:"Record shops, small concerts, and long walks home.", symbol:"sun.max.fill")
    @State private var demoSelfNote = "My favorite part of a concert is the walk home talking about the set. I’d love to meet someone who wants to trade playlists and try a new venue."
    @State private var demoPortrait = "You enjoy music as a way to get to know someone. A small show with time to talk afterward sounds like your kind of first date."
    @State private var demoMeetingNote = "Remy and I got talking about record shops. We traded favorite albums, and I wanted the conversation to keep going. I’d like to invite them to Sunday's record fair."
    @State private var demoMeetingReflection = "You felt at ease once you had a shared subject. The record fair gives you a specific reason to reconnect. Would you enjoy browsing together even if you came home empty-handed?"
    private var saved: [DateProfile] { demo ? demoSaved : liveSaved }
    private var profileBinding: Binding<DateProfile> { demo ? $demoProfile : $liveProfile }
    private var profile: DateProfile { profileBinding.wrappedValue }
    @State private var tab = 0
    @AppStorage("openDate.selfNote") private var selfNote=""
    @AppStorage("openDate.selfReflection") private var selfReflection=""
    @AppStorage("openDate.encounterNote") private var encounterNote=""
    @AppStorage("openDate.encounterReflection") private var encounterReflection=""
    @State private var working=false
    @State private var distance = 0.35
    @State private var liveProfile: DateProfile = {
        if let data = UserDefaults.standard.data(forKey:"openDate.profile"), let saved = try? JSONDecoder().decode(DateProfile.self,from:data) { return saved }
        return DateProfile(name:"Guest",interests:["Design","Music"],lookingFor:"Someone to explore with",symbol:"sun.max.fill")
    }()
    private var nearby: [Encounter] {
        guard open else { return [] }
        let floorPeople = building.people.enumerated().filter { !roomOnly || $0.offset == currentRoom }.map(\.element)
        let pool = demo ? floorPeople.map { Encounter(profile:$0,strength:-65) } : room.peers.filter {
            !floorCode.isEmpty && $0.profile.floorCode == normalizedFloorCode
        }
        return pool.filter { !dismissed.contains($0.id) }.sorted {
            let a = score($0.profile), b = score($1.profile)
            return a == b ? $0.profile.name < $1.profile.name : a > b
        }
    }
    private var normalizedFloorCode: String { floorCode.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() }
    private func startOnFloor() {
        var advertised = liveProfile
        advertised.floorCode = normalizedFloorCode
        room.start(advertised)
    }
    private func common(_ p:DateProfile) -> [String] { profile.interests.filter(p.interests.contains) }
    private func score(_ p:DateProfile) -> Int { common(p).count * 2 + (profile.lookingFor == p.lookingFor ? 1 : 0) }
    private var candidate: Encounter? { nearby.first { score($0.profile)>0 && $0.strength >= -72 && !alerted.contains($0.id) } }
    private func match() {
        guard instant, open, banner == nil, selected == nil, let encounter=candidate else {return}
        banner=encounter.profile; alerted.insert(encounter.id)
        UINotificationFeedbackGenerator().notificationOccurred(.success)
        let note=UNMutableNotificationContent();note.title=demo ? "Open Date · Demo match" : "Open Date · Nearby match"
        note.body="Someone nearby shares your preferences. Open the room to see your signal."
        UNUserNotificationCenter.current().getNotificationSettings { settings in
            guard settings.authorizationStatus == .authorized else {return}
            UNUserNotificationCenter.current().add(UNNotificationRequest(identifier:"open-date-nearby",content:note,trigger:nil))
        }
    }
    private func leave() { likes=[]; open=false; instant=false; banner=nil; selected=nil; dismissed=[]; alerted=[]; room.stop() }
    private func find(_ p:DateProfile) { banner=nil; distance=0.35; selected=p }
    private func skip(_ p:DateProfile) { vexo.send("reject", to:p.name); dismissed.insert(p.id); banner=nil; selected=nil }
    private func remember(_ p:DateProfile) {
        guard !saved.contains(where:{$0.id==p.id}) else { return }
        if demo { demoSaved.append(p); return }
        liveSaved.append(p)
        UserDefaults.standard.set(try? JSONEncoder().encode(liveSaved),forKey:"openDate.matches")
    }
    private func like(_ p:DateProfile) {
        likes.insert(p.id); vexo.send("accept", to:p.name)
        if demo { remember(p) }
        else { room.like(p.id); if room.incoming.contains(p.id) {remember(p)} }
        detail=nil
    }
    var body: some View {
        TabView(selection:$tab) {
            discovery.tabItem{Label("Discover",systemImage:"dot.radiowaves.left.and.right")}.tag(0)
            journal(afterMeeting:false).tabItem{Label("Second You",systemImage:"person.text.rectangle")}.tag(1)
            matches.tabItem{Label("Matches",systemImage:"heart")}.tag(2)
            journal(afterMeeting:true).tabItem{Label("Analyze",systemImage:"text.bubble")}.tag(3)
        }.tint(rose).preferredColorScheme(.light)
        .onAppear { vexo.start(name:profile.name) }
        .onChange(of:profile.name) { vexo.start(name:$0) }
        .onChange(of:room.incoming){ ids in
            for p in nearby.map(\.profile) where ids.contains(p.id) && likes.contains(p.id) {remember(p)}
        }
        .sheet(item: $directory, onDismiss: {
            if let person = directorySelection { detail = person; directorySelection = nil }
        }) { group in
            NavigationStack {
                List(group.people) { person in
                    Button {
                        directorySelection = person
                        directory = nil
                    } label: {
                        HStack {
                            ProfilePortrait(person: person, size: 42)
                            VStack(alignment: .leading) {
                                Text(person.name).font(.headline)
                                Text(person.interests.joined(separator: " · ")).font(.caption)
                            }
                        }
                    }.buttonStyle(.plain)
                }.navigationTitle(group.title)
                    .toolbar { Button("Done") { directory = nil } }
            }
        }
        .sheet(isPresented:$editing){editor}
        .sheet(item:$selected){p in signal(p)}
        .sheet(item:$detail){p in
            VStack(alignment:.leading,spacing:20){
                ProfilePortrait(person: p, size: 68)
                Text(p.name).font(.system(size:38,design:.serif))
                Text(p.lookingFor).font(.title3)
                Text(p.interests.joined(separator:"  ·  "));if let personality=p.personality,!personality.isEmpty{Text(personality)}
                if demo {Text("Fictional demo profile · likes you back").font(.caption).foregroundStyle(.secondary)}
                if saved.contains(where:{$0.id==p.id}) {Button("View match"){detail=nil;tab=2}}
                else {Button(likes.contains(p.id) ? "Send interest again" : "Like "+p.name){like(p)}.buttonStyle(.borderedProminent)}
                Button("Pass"){skip(p);detail=nil}
            }.padding(28).frame(maxWidth:.infinity,alignment:.leading).presentationDetents([.medium,.large]).tint(rose)
        }
    }
    private var matches:some View {
        NavigationStack {List {
            if saved.isEmpty {Text("Like someone in Discover. When you both like each other, you’ll see your match here.")}
            if demo {Text("Demo matches · fictional people").font(.caption).foregroundStyle(.secondary)}
            ForEach(saved){p in VStack(alignment:.leading,spacing:8){
                Text(p.name).font(.title2.bold());Text(p.lookingFor);Text(p.interests.joined(separator:" · ")).foregroundStyle(.secondary)
                if open && nearby.contains(where:{$0.id==p.id}) {Button("Find each other offline"){find(p)}}
                else {Text("Outside the current room").font(.caption)}
            }.padding(.vertical,6)}.onDelete{offsets in if demo {demoSaved.remove(atOffsets:offsets);return};liveSaved.remove(atOffsets:offsets);UserDefaults.standard.set(try? JSONEncoder().encode(liveSaved),forKey:"openDate.matches")}
        }.navigationTitle("Matches")}
    }
    private func journal(afterMeeting:Bool)->some View {
        let input = demo ? (afterMeeting ? $demoMeetingNote : $demoSelfNote) : (afterMeeting ? $encounterNote : $selfNote)
        let reflection = demo ? (afterMeeting ? $demoMeetingReflection : $demoPortrait) : (afterMeeting ? $encounterReflection : $selfReflection)
        return NavigationStack {Form {
            if demo {Section {Label(afterMeeting ? "Demo · After meeting Remy" : "Demo · Sam’s portrait", systemImage:afterMeeting ? "text.bubble" : "person.crop.circle").font(.headline)}}
            if !afterMeeting {Section("Dating profile"){Button("Edit interests and preferences"){editing=true};Text(profile.lookingFor)}}
            Section(afterMeeting ? "After meeting someone" : "In your own words"){
                Text(afterMeeting ? "Write or dictate what you noticed and how you felt." : "Write or dictate what you enjoy, what you value, and who you hope to meet.").font(.subheadline)
                TextEditor(text:input).frame(minHeight:100)
                Button(working ? "Working…" : afterMeeting ? "Reflect on this meeting" : "Build my portrait"){
                    working=true
                    Task {let result=await PersonalInsights.reflect(text:input.wrappedValue,profile:profile,afterMeeting:afterMeeting)
                        reflection.wrappedValue=result;working=false}
                }.disabled(working || input.wrappedValue.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty)
            }
            let result=reflection.wrappedValue
            if !result.isEmpty {Section("Private reflection"){Text(result).textSelection(.enabled)}}
        }.navigationTitle(afterMeeting ? "Analyze" : "Second You")
        }
    }
    private var discovery: some View {
        ScrollView {
            VStack(alignment:.leading,spacing:20) {
                HStack {
                    Image(systemName:"circle.hexagongrid.fill").foregroundStyle(rose)
                    Text("OPEN DATE").font(.system(.subheadline,design:.rounded).weight(.bold)).tracking(2)
                    Spacer()
                    Button { editing=true } label:{ MyAvatar() }.accessibilityLabel("Edit my profile")
                }
                if demo {
                        HStack {
                            Text("Around you").font(.system(.title, design: .serif))
                            Spacer()
                            Button(open ? "Leave" : "Enter") { if open { leave() } else { open = true } }
                        }
                        if open {
                            DeviceMap(people: nearby.map(\.profile)) { members in
                                directory = PeopleDirectory(title: "Here on the map", people: members)
                            }
                        }
                } else {
                VStack(alignment:.leading,spacing:16){
                    HStack { Image(systemName:"dot.radiowaves.left.and.right"); Text(demo ? "SIMULATED ROOM":"BLUETOOTH ROOM").font(.caption.bold()).tracking(1.6);Spacer() }
                    Text(open ? "Open to meet." : "Open to date?").font(.system(size:41,weight:.medium,design:.serif))
                    Text(open ? (demo ? "You’re here as \(profile.name). Tap a profile to see what you have in common, or find Remy in Matches." : room.status) : (demo ? "Try the experience with three fictional people." : "Share your chosen name, interests and dating preferences with other opted-in phones nearby.")).font(.subheadline)
                    if !open {
                        TextField("Building + floor code", text: $floorCode)
                            .textFieldStyle(.roundedBorder).foregroundStyle(plum)
                        Text("Enter the same building and floor code as others on your floor.").font(.footnote)
                    } else {
                        Text("Checked in · " + normalizedFloorCode)
                        Text("\(nearby.count) others on this floor").font(.headline)
                    }
                    Button(open ? "Leave room" : "Enter room"){if open {leave()} else {open=true;if !demo {startOnFloor()}}}
                        .disabled(!open && normalizedFloorCode.isEmpty).buttonStyle(.borderedProminent).tint(.white).foregroundStyle(plum)
                }.foregroundStyle(.white).padding(24).frame(maxWidth:.infinity,alignment:.leading).background(plum,in:RoundedRectangle(cornerRadius:26))
                }
                if open {
                    Toggle("Instant matching",isOn:$instant).font(.headline).tint(rose)
                        .onChange(of:instant){ enabled in if enabled { UNUserNotificationCenter.current().requestAuthorization(options:[.alert,.sound]){ _,_ in }; match() } else {banner=nil} }
                    if let p=banner {
                        VStack(alignment:.leading,spacing:9){Label("Instant match",systemImage:"sparkles").font(.caption.bold());Text("\(p.name) is nearby").font(.title3.bold())
                            HStack {Button("View profile"){banner=nil;detail=p}.buttonStyle(.borderedProminent);Button("Pass"){skip(p)}}
                        }.padding().frame(maxWidth:.infinity,alignment:.leading).background(Color.pink.opacity(0.09),in:RoundedRectangle(cornerRadius:18))
                    }
                    directoryButton("Open to date", people: nearby.map(\.profile))
                    if nearby.isEmpty {
                        Text("No one else is open to date here yet.").foregroundStyle(.secondary)
                    } else {
                        ScrollView(.horizontal) {
                            LazyHStack(spacing: 16) {
                                ForEach(nearby) { encounter in
                                    Button { detail = encounter.profile } label: {
                                        VStack {
                                            ProfilePortrait(person: encounter.profile, size: 52)
                                            Text(encounter.profile.name).font(.subheadline)
                                        }
                                    }.buttonStyle(.plain)
                                }
                            }.padding(.vertical, 2)
                        }.scrollIndicators(.hidden)
                    }
                    let recommendations = nearby.filter { score($0.profile) >= 3 }
                    directoryButton("High compatibility", people: recommendations.map(\.profile))
                    if recommendations.isEmpty {
                        Text("No close preference matches here yet.").foregroundStyle(.secondary)
                    }
                    ForEach(recommendations.prefix(12)) { encounter in
                        let person = encounter.profile
                        Button { detail = person } label: {
                            HStack(spacing: 12) {
                                ProfilePortrait(person: person, size: 44)
                                VStack(alignment: .leading) {
                                    Text(person.name).font(.headline)
                                    Text("Both into " + common(person).joined(separator: " & ")).font(.subheadline)
                                }
                                Spacer()
                                Image(systemName: "chevron.right").font(.caption)
                            }.padding().background(.white, in: RoundedRectangle(cornerRadius: 16))
                        }.buttonStyle(.plain)
                    }
                }
            }.padding(20)
        }.background(Color(red:0.98,green:0.96,blue:0.94)).foregroundStyle(plum).tint(rose)
        .onChange(of: nearby.map(\.id)) { _, ids in
            if let current = banner, !ids.contains(current.id) { banner = nil }
        }
        .onChange(of:candidate?.id){_ in match()}


    }
    @State private var photoItem: PhotosPickerItem?
    @AppStorage("openDate.avatarBytes") private var avatarBytes = Data()
    @State private var directory: PeopleDirectory?
    @State private var directorySelection: DateProfile?
    private func directoryButton(_ title: String, people: [DateProfile]) -> some View {
        Button {
            directory = PeopleDirectory(title: title, people: people)
        } label: {
            HStack {
                Text(title).font(.system(.title, design: .serif))
                Spacer()
                Text("\(people.count)").monospacedDigit()
                Image(systemName: "chevron.right").font(.caption)
            }
        }.buttonStyle(.plain)
    }
    private var editor: some View {
        NavigationStack {Form {
            Section {
                PhotosPicker(selection: $photoItem, matching: .images) {
                    HStack { MyAvatar(); Text("Choose profile photo") }
                }.task(id: photoItem) {
                    guard let data = try? await photoItem?.loadTransferable(type: Data.self),
                          let image = UIImage(data: data),
                          let thumb = await image.byPreparingThumbnail(ofSize: CGSize(width: 240, height: 240)),
                          !Task.isCancelled, let jpg = thumb.jpegData(compressionQuality: 0.85) else { return }
                    avatarBytes = jpg
                }
            }
            Section("Your room profile"){ TextField("First name",text:profileBinding.name)
                TextField("How you describe yourself", text: Binding(get:{profile.personality ?? ""},set:{profileBinding.wrappedValue.personality=String($0.prefix(160))}))
                Picker("Looking for",selection:profileBinding.lookingFor){ForEach(["Someone to explore with","An adventure buddy","A creative collaborator"],id:\.self){Text($0)}}
            }
            Section("Your interests"){ForEach(DateProfile.choices,id:\.self){interest in
                Button{if profile.interests.contains(interest){profileBinding.wrappedValue.interests.removeAll{$0==interest}} else {profileBinding.wrappedValue.interests.append(interest)}}label:{HStack{Text(interest);Spacer();if profile.interests.contains(interest){Image(systemName:"checkmark")}}}
            }}
        }.navigationTitle("Your profile").toolbar {Button("Done"){editing=false}.disabled(profile.name.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty)}
        }.onDisappear {
            profileBinding.wrappedValue.name=String(profile.name.trimmingCharacters(in:.whitespacesAndNewlines).prefix(40));if profile.name.isEmpty {profileBinding.wrappedValue.name="Guest"}
            guard !demo else {return}
            UserDefaults.standard.set(try? JSONEncoder().encode(profile),forKey:"openDate.profile")
            if open && !demo {startOnFloor()}
        }
    }
    private func signal(_ p:DateProfile)->some View {
        let live=nearby.first{$0.id==p.id}
        let level=demo ? distance : min(1,max(0,Double((live?.strength ?? -95)+95)/55))
        let pair=[p.id.uuidString,profile.id.uuidString].sorted().joined().utf8.reduce(0){($0+Int($1))%360}
        let shape=DateProfile.cues[pair % DateProfile.cues.count]
        let glow=Color(hue:Double(pair)/360,saturation:0.72,brightness:1)
        return VStack(spacing:20){
            HStack{Text(demo ? "DEMO SIGNAL":"SHARED SIGNAL").font(.caption.bold()).tracking(2);Spacer();Button("Close"){selected=nil}};Spacer()
            ZStack {Circle().fill(glow.opacity(0.12+level*0.25)).frame(width:160+60*level,height:160+60*level);Image(systemName:shape).font(.system(size:62)).foregroundStyle(glow.opacity(0.4+level*0.6)).shadow(color:glow,radius:level*18)}
            Text("Find "+p.name).font(.system(size:36,design:.serif));Text(demo ? "Move closer to brighten your shared signal." : live == nil ? "Signal lost. Return to the room to find someone nearby." : "Choose each other on both phones to see the same symbol and color. A stronger Bluetooth signal brightens it.").multilineTextAlignment(.center)
            if demo {Slider(value:$distance,in:0...1).accessibilityLabel("Simulated proximity");HStack{Text("Farther");Spacer();Text("Closer")}.font(.caption)}
            Spacer();Button("Pass on this connection"){skip(p)}.buttonStyle(.bordered)
        }.padding(30).frame(maxWidth:.infinity,maxHeight:.infinity).background(plum).foregroundStyle(.white).tint(glow)
    }
}

private enum DemoBuilding: String, CaseIterable {
    case exchange = "The Exchange"
    case pavilion = "Garden Pavilion"

    var rooms: [String] {
        self == .exchange ? ["Atrium", "Studio", "Café"] : ["Gallery", "Workshop", "Lounge"]
    }

    var people: [DateProfile] {
        if self == .exchange { return DemoCrowd.people }
        return [Self.noor]
    }

    static let noor = DateProfile(id: UUID(uuidString: "00000000-0000-4000-A000-000000000004")!, name: "Noor", interests: ["Design", "Film"], lookingFor: "A creative collaborator", personality: "I spend Saturdays sketching at galleries.", symbol: "sparkles")

    // Relative floor coordinates, with a continuous corridor between the rooms.
    func bounds(for index: Int) -> CGRect {
        let split: CGFloat = self == .exchange ? 0.53 : 0.40
        let above: CGFloat = self == .exchange ? 0.48 : 0.61
        if index == 0 { return CGRect(x: 0.05, y: 0.08, width: split - 0.09, height: 0.84) }
        return CGRect(x: split + 0.05, y: index == 1 ? 0.08 : above + 0.06,
                      width: 0.90 - split, height: index == 1 ? above - 0.10 : 0.86 - above)
    }
}

private struct IndoorPlan: View {
    let building: DemoBuilding
    @Binding var currentRoom: Int
    let people: [DateProfile]
    let select: (DateProfile) -> Void
    private let ink = Color(red: 0.20, green: 0.29, blue: 0.25)

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Label(building.rooms[currentRoom], systemImage: "location.fill").font(.headline)
                Spacer()
                Text("Floor 1").font(.caption)
            }.padding(14)
            GeometryReader { geo in
                ZStack(alignment: .topLeading) {
                    Color(red: 0.92, green: 0.93, blue: 0.89)
                    ForEach(building.rooms.indices, id: \.self) { i in
                        let r = building.bounds(for: i).applying(CGAffineTransform(scaleX: geo.size.width, y: geo.size.height))
                        let active = currentRoom == i
                        ZStack(alignment: .topLeading) {
                            Rectangle().fill(active ? Color(red: 0.83, green: 0.89, blue: 0.81) : Color(red: 0.97, green: 0.95, blue: 0.89))
                            Rectangle().strokeBorder(ink.opacity(0.56), lineWidth: 2)
                            // Leave an opening in the corridor-facing wall.
                            Rectangle().fill(Color(red: 0.92, green: 0.93, blue: 0.89)).frame(width: 3, height: 18)
                                .position(x: i == 0 ? r.width - 1 : 1, y: r.height * 0.65)
                            Text(building.rooms[i].uppercased()).font(.caption2.bold()).tracking(1).padding(9)
                        }.frame(width: r.width, height: r.height).contentShape(Rectangle())
                            .onTapGesture { withAnimation { currentRoom = i } }
                            .accessibilityElement(children: .ignore).accessibilityLabel("Move to " + building.rooms[i])
                            .accessibilityAddTraits(.isButton)
                            .position(x: r.midX, y: r.midY)
                        if active {
                            MyAvatar().position(x: r.midX, y: r.maxY - 22).allowsHitTesting(false)
                        }
                        if let person = building.people.dropFirst(i).first, people.contains(where: { $0.id == person.id }) {
                            Button { select(person) } label: {
                                VStack(spacing: 1) {
                                    ProfilePortrait(person: person, size: 35)
                                    Text(person.name).font(.caption2.bold())
                                }
                            }.buttonStyle(.plain).accessibilityLabel("View " + person.name)
                                .position(x: r.midX, y: r.midY)
                        }
                    }
                }
            }.frame(height: 340)
        }.foregroundStyle(ink).background(.white, in: RoundedRectangle(cornerRadius: 20))
            .clipShape(RoundedRectangle(cornerRadius: 20))
    }
}

private struct ProfilePortrait: View {
    let person: DateProfile
    let size: CGFloat

    var body: some View {
        let index = DemoCrowd.indices[person.id]
        let resource = index.map { $0 < 3 ? DateProfile.examples[$0].name.lowercased() : "guest" + String($0 - 3) } ?? (person.id == DemoBuilding.noor.id ? "noor" : "")
        Group {
            if !resource.isEmpty, let photo = UIImage(named: "Portraits/" + resource + ".jpg") {
                Image(uiImage: photo).resizable().scaledToFill()
            } else {
                Image(systemName: "person.crop.circle.fill").resizable().foregroundStyle(.teal, .white)
            }
        }.frame(width: size, height: size).clipShape(Circle())
            .overlay(Circle().strokeBorder(.white, lineWidth: 1.5))
            .accessibilityLabel(person.name)
    }
}

private struct MyAvatar: View {
    @AppStorage("openDate.avatarBytes") private var bytes = Data()
    var body: some View {
        Group {
            if let photo = UIImage(data: bytes) {
                Image(uiImage: photo).resizable().scaledToFill()
            } else {
                Image(systemName: "person.crop.circle.fill").resizable().foregroundStyle(.teal, .white)
            }
        }.frame(width: 40, height: 40).clipShape(Circle())
            .overlay(Circle().stroke(.white, lineWidth: 2)).shadow(radius: 2).accessibilityLabel("Your location")
    }
}

private final class DevicePosition: NSObject, ObservableObject, CLLocationManagerDelegate {
    @Published var fix: CLLocation?
    @Published var message = "Finding your location…"
    private let manager = CLLocationManager()
    private var running = false
    private var timer: Timer?
    func start() {
        running = true
        #if targetEnvironment(simulator)
        readMac()
        timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in self?.readMac() }
        #else
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyBest
        manager.distanceFilter = kCLDistanceFilterNone
        if manager.authorizationStatus == .notDetermined { manager.requestWhenInUseAuthorization() }
        else { locationManagerDidChangeAuthorization(manager) }
        #endif
    }
    func stop() {
        running = false
        manager.stopUpdatingLocation()
        timer?.invalidate()
        timer = nil
        fix = nil
    }
    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        guard running else { return }
        switch manager.authorizationStatus {
        case .authorizedWhenInUse, .authorizedAlways: manager.startUpdatingLocation()
        case .denied, .restricted: fix = nil; message = "Allow location for Open Date in Settings."
        default: break
        }
    }
    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard running, let last = locations.last, last.horizontalAccuracy >= 0, abs(last.timestamp.timeIntervalSinceNow) < 60 else { return }
        fix = last
    }
    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        fix = nil
        message = "Waiting for a location signal…"
    }
    #if targetEnvironment(simulator)
    private func readMac() {
        let cache = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
        try? Data().write(to: cache.appendingPathComponent("location-request"))
        guard let data = try? Data(contentsOf: cache.appendingPathComponent("mac-location")),
              let packet = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let t = packet["time"] as? Double, abs(Date().timeIntervalSince1970 - t) < 60 else {
            fix = nil; message = "Waiting for Mac location…"; return
        }
        guard let lat = packet["lat"] as? Double, let lon = packet["lon"] as? Double, let accuracy = packet["accuracy"] as? Double else {
            fix = nil; message = packet["status"] as? String ?? "Waiting for Mac location…"; return
        }
        fix = CLLocation(coordinate: .init(latitude: lat, longitude: lon), altitude: 0, horizontalAccuracy: accuracy, verticalAccuracy: -1, timestamp: Date(timeIntervalSince1970: t))
    }
    #endif
}

private struct PeopleDirectory: Identifiable {
    let id = UUID()
    let title: String
    let people: [DateProfile]
}

// 180 attendees including the viewer; only these 120 fictional attendees opted in.
private enum DemoCrowd {
    static let people: [DateProfile] = DateProfile.examples + (0..<117).map { i in
        let names = "Alex Maya Leo Zoe Kai Mina Theo Nina Luca Iris Owen Eva Finn Ada Max Lia Nico Tess Eli June Beau Hana Milo Sana Ravi Mira Rowan Olive Ezra Wren".components(separatedBy: " ")
        let suffix = ["A.", "B.", "C.", "D."][i / names.count]
        let interests = DateProfile.choices
        let first = i % interests.count
        let second = (first + 1 + (i / interests.count) % (interests.count - 1)) % interests.count
        let goals = ["Someone to explore with", "An adventure buddy", "A creative collaborator"]
        let id = UUID(uuidString: String(format: "10000000-0000-4000-A000-%012d", i))!
        return DateProfile(id: id, name: names[i % names.count] + " " + suffix,
                           interests: [interests[first], interests[second]],
                           lookingFor: goals[(i + i / interests.count) % goals.count], symbol: "sparkles")
    }
    static let indices = Dictionary(uniqueKeysWithValues: people.enumerated().map { ($0.element.id, $0.offset) })
}

private struct DeviceMap: View {
    let people: [DateProfile]
    let showGroup: ([DateProfile]) -> Void
    @StateObject private var position = DevicePosition()
    @State private var anchor: CLLocationCoordinate2D?
    @State private var camera: MapCameraPosition = .automatic

    var body: some View {
        VStack(alignment: .leading) {
            if let fix = position.fix {
                Map(position: $camera) {
                    Annotation("", coordinate: fix.coordinate) { MyAvatar() }
                    if let anchor {
                        ForEach(0..<6, id: \.self) { index in
                            let members = people.filter { (DemoCrowd.indices[$0.id] ?? 0) % 6 == index }
                            if let first = members.first {
                                let angle = Double(index) * .pi / 3
                                let spot = CLLocationCoordinate2D(latitude: anchor.latitude + 16 * cos(angle) / 111_000,
                                                                  longitude: anchor.longitude + 17 * sin(angle) / (111_000 * max(0.01, cos(anchor.latitude * .pi / 180))))
                                Annotation("", coordinate: spot) {
                                    Button { showGroup(members) } label: {
                                        ProfilePortrait(person: first, size: 38)
                                            .overlay(alignment: .bottomTrailing) {
                                                Text("\(members.count)").font(.caption2.bold()).padding(3)
                                                    .foregroundStyle(.white).background(.black, in: Capsule()).offset(x: 6, y: 3)
                                            }
                                    }.accessibilityLabel("\(members.count) people here")
                                }
                            }
                        }
                    }
                }.frame(height: 340).clipShape(RoundedRectangle(cornerRadius: 18))
                Text("Your location ±\(Int(fix.horizontalAccuracy.rounded())) m · \(people.count) open · 180 demo attendees").font(.footnote)
            } else {
                Label(position.message, systemImage: "location").frame(maxWidth: .infinity, minHeight: 190)
            }
        }.onAppear { position.start() }.onDisappear { position.stop() }
            .onChange(of: position.fix) { _, new in
                guard let fix = new else { return }
                if anchor == nil { anchor = fix.coordinate }
                camera = .region(MKCoordinateRegion(center: fix.coordinate, latitudinalMeters: 56, longitudinalMeters: 56))
            }
    }
}
