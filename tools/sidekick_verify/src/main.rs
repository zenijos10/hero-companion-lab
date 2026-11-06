//! sidekick-verify <bundle.json.gz> <file.skif>...
//! Decodes each file with Sidekick's own reader against the pinned dataset and
//! fails if any file is refused or leaves anything unresolved.
use coh_data::{skif, PowerDatabase};

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let (bundle, files) = args.split_first().expect("usage: sidekick-verify <bundle.json.gz> <file.skif>...");
    assert!(!files.is_empty(), "no .skif files given");
    let bytes = std::fs::read(bundle).expect("read bundle");
    let database = PowerDatabase::from_gz_bytes(&bytes).expect("load Sidekick dataset");
    let mut failed = 0;
    for file in files {
        let text = std::fs::read_to_string(file).expect("read .skif");
        match skif::decode(&text, &database) {
            Ok(decoded) if decoded.unresolved.is_empty() => println!("OK          {file}"),
            Ok(decoded) => {
                failed += 1;
                for item in &decoded.unresolved {
                    println!("UNRESOLVED  {file}: {}: {}", item.context, item.detail);
                }
            }
            Err(error) => {
                failed += 1;
                println!("REFUSED     {file}: {error}");
            }
        }
    }
    println!("{} of {} files re-opened cleanly by Sidekick", files.len() - failed, files.len());
    std::process::exit(if failed == 0 { 0 } else { 1 });
}
