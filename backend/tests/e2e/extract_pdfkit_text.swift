import Foundation
import PDFKit

enum ExtractionError: Error {
    case invalidArguments
    case unreadablePDF
}

guard CommandLine.arguments.count == 2 else {
    throw ExtractionError.invalidArguments
}
let url = URL(fileURLWithPath: CommandLine.arguments[1])
guard let document = PDFDocument(url: url) else {
    throw ExtractionError.unreadablePDF
}
let pages = (0..<document.pageCount).map { document.page(at: $0)?.string ?? "" }
let data = try JSONSerialization.data(withJSONObject: pages)
FileHandle.standardOutput.write(data)
