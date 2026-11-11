"""The audited pretrained candidates, pinned to an exact Hub revision.

Every hash below was checked on 5 November 2026 against the Hub's LFS SHA-256 and git blob IDs at
the pinned revision and, for Horizon-Labs, against the publisher's own `SHA256SUMS`. A new
revision is a new entry after a new audit, never an edit in place.

Only the selected candidate lists the files needed to run it. The others record the weights hash
for reference and cannot be fetched.
"""

import re
from dataclasses import dataclass

HUB_HOST = "huggingface.co"
# Redirect targets for Hub downloads. Integrity comes from the pinned hashes; the host list is a
# second guard so a redirect cannot fetch from elsewhere.
ALLOWED_HOSTS = (HUB_HOST, "us.aws.cdn.hf.co", "cdn-lfs.hf.co", "cdn-lfs-us-1.hf.co")
# Only data formats that cannot execute code on load. Pickle-based files (.bin, .pt, .pth, .pkl,
# .ckpt) are never fetched or loaded.
ALLOWED_SUFFIXES = (".json", ".safetensors")
ALLOWED_PLAIN_NAMES = ("LICENSE", "NOTICE")
FORBIDDEN_SUFFIXES = (".bin", ".pt", ".pth", ".pkl", ".pickle", ".ckpt", ".joblib", ".h5", ".py")
REVISION = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ModelFile:
    name: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class Candidate:
    key: str
    repo: str
    revision: str
    license: str
    base_model: str
    parameters: str
    labels: tuple[str, ...]  # in output-index order, as in the pinned config.json
    fraud_labels: tuple[str, ...]  # labels whose probability is the phishing/fraud score
    spam_labels: tuple[str, ...]
    max_tokens: int
    files: tuple[ModelFile, ...]
    selected: bool
    decision: str

    @property
    def weights(self) -> ModelFile:
        return next(f for f in self.files if f.name.endswith(".safetensors"))


def allowed_file_name(name: str) -> bool:
    if "/" in name or "\\" in name or name.startswith("."):
        return False
    if name.lower().endswith(FORBIDDEN_SUFFIXES):
        return False
    return name.endswith(ALLOWED_SUFFIXES) or name in ALLOWED_PLAIN_NAMES


HORIZON = Candidate(
    key="horizon-phishing-scam-base",
    repo="Horizon-Labs/phishing-scam-detector-base",
    revision="fa686fc0d6a3634092ada93a7c6b89ab0746b8f8",
    license="Apache-2.0 (weights and tokenizer derive from MIT-licensed mmBERT-base; NOTICE kept)",
    base_model="jhu-clsp/mmBERT-base (ModernBERT)",
    parameters="307M",
    labels=("legitimate", "spam", "fraud"),
    fraud_labels=("fraud",),
    spam_labels=("spam",),
    max_tokens=256,
    files=(
        ModelFile(
            "config.json", "99b40411e6748ebc586843956cd36377fc928f2d743395f136a9a15ce464daa9", 2068
        ),
        ModelFile(
            "special_tokens_map.json",
            "baec30ea10906f16adb8c18af7a34023002c1746542612b8b41c9f09e1351351",
            636,
        ),
        ModelFile(
            "tokenizer_config.json",
            "1d2f82c1341a79748e00efe82e67690f99d00b3c2a894f2b23128fd9d3519da3",
            46440,
        ),
        ModelFile(
            "tokenizer.json",
            "e7322a5d841fcfe921a2457104f85e5bfd2fbb03cdbbe495ce6c04365b9f670a",
            34363286,
        ),
        ModelFile(
            "model.safetensors",
            "1f056ed61f8c0f6bfb11616e9c2f640762dcbbaff92bdb71657723f1d84125af",
            1230144500,
        ),
        ModelFile(
            "LICENSE", "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30", 11358
        ),
        ModelFile(
            "NOTICE", "52bb89a98d1f7e7bda75f7bbef665f57631b20601c19e8da6ee21e73a7c80cd6", 1562
        ),
    ),
    selected=True,
    decision="selected: separate fraud label; trained on synthetic text, so independent of "
    "UCI, Mishra and IMC as far as published",
)

OPEN_TEXT_SHIELD = Candidate(
    key="opentextshield",
    repo="telecomsxchange/OpenTextShield",
    revision="9e839db78bd1daff8062ae2f2638af0b64b416ae",
    license="MIT",
    base_model="google-bert/bert-base-multilingual-cased",
    parameters="~180M",
    labels=("ham", "spam", "phishing"),
    fraud_labels=("phishing",),
    spam_labels=("spam",),
    max_tokens=96,
    files=(
        ModelFile(
            "model.safetensors",
            "8e5f65efc7fecafc8280b8a817215f80738871d4da206bab94cce1ca43781fe9",
            711446532,
        ),
    ),
    selected=False,
    decision="runner-up: trained on UCI and Mishra & Soni texts verbatim (publisher's report), so "
    "it cannot be evaluated on them; publisher reports phishing collapsing into spam",
)

SCAMSHIELD = Candidate(
    key="scamshield",
    repo="rehan-ml/scamshield-scam-detector",
    revision="0aca58d73bc34d17b247496aa5216fd04aaa39aa",
    license="MIT",
    base_model="distilbert-base-uncased",
    parameters="67M",
    labels=("LABEL_0", "LABEL_1"),  # card: 0 = safe, 1 = scam; config has no label map
    fraud_labels=("LABEL_1",),
    spam_labels=(),
    max_tokens=512,
    files=(
        ModelFile(
            "model.safetensors",
            "3d72250279537ef4653e22a0fc939e236056bdfb4badf446f198417f9bbda84f",
            267832560,
        ),
    ),
    selected=False,
    decision="rejected: binary scam/safe trained on UCI spam as scam (no spam/phishing "
    "separation), job-offer focus, no label map, ships a pickle training_args.bin",
)

CANDIDATES = {c.key: c for c in (HORIZON, OPEN_TEXT_SHIELD, SCAMSHIELD)}


def selected() -> Candidate:
    chosen = [c for c in CANDIDATES.values() if c.selected]
    if len(chosen) != 1:
        raise RuntimeError("Exactly one candidate must be selected")
    return chosen[0]
