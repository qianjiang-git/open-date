// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "SecondYouKit",
    platforms: [.iOS("26.0"), .macOS("26.0")],
    products: [
        .library(name: "SecondYouKit", targets: ["SecondYouKit"]),
        .executable(name: "secondyou-demo", targets: ["SecondYouDemo"]),
    ],
    targets: [
        .target(name: "SecondYouKit"),
        .executableTarget(name: "SecondYouDemo", dependencies: ["SecondYouKit"]),
        .testTarget(name: "SecondYouKitTests", dependencies: ["SecondYouKit"]),
    ]
)
