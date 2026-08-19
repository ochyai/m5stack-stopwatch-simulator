// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "M5StackSimulator",
    platforms: [
        .macOS(.v13),
    ],
    products: [
        .library(name: "SimulatorBridge", targets: ["SimulatorBridge"]),
        .executable(name: "M5StackSimulator", targets: ["M5StackSimulator"]),
    ],
    targets: [
        .target(name: "SimulatorBridge"),
        .executableTarget(
            name: "M5StackSimulator",
            dependencies: ["SimulatorBridge"],
            linkerSettings: [
                .linkedFramework("AppKit"),
                .linkedFramework("WebKit"),
            ]
        ),
        .testTarget(
            name: "SimulatorBridgeTests",
            dependencies: ["SimulatorBridge"]
        ),
    ]
)
