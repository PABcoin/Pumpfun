"""
pump_fun.py — Integrasi dengan pump.fun / pumpportal.fun API

Flow:
  1. upload_metadata_to_ipfs() — upload gambar + metadata ke IPFS gratis (tanpa API key)
  2. create_token_transaction() — POST ke pumpportal /api/trade-local, sign dg 2 keypair, kirim via RPC

Catatan penting (April 2025):
  - pump.fun/api/ipfs sudah MATI
  - Endpoint create BUKAN /api/create → gunakan /api/trade-local
  - Transaksi harus di-sign oleh DUA keypair: mint keypair + signer keypair
  - IPFS upload menggunakan nft-storage.letsbonk22.workers.dev (gratis, tanpa API key)
"""

import os
import json
import base64
import logging

import httpx
from solders.keypair import Keypair                   # type: ignore
from solders.transaction import VersionedTransaction   # type: ignore

logger = logging.getLogger(__name__)

# Endpoint yang benar (per dokumentasi pumpportal)
IPFS_IMG_URL   = "https://nft-storage.letsbonk22.workers.dev/upload/img"
IPFS_META_URL  = "https://nft-storage.letsbonk22.workers.dev/upload/meta"
PUMPPORTAL_LOCAL = "https://pumpportal.fun/api/trade-local"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_keypair() -> Keypair:
    """Muat Solana keypair dari environment variable WALLET_PRIVATE_KEY."""
    raw = os.environ.get("WALLET_PRIVATE_KEY", "").strip()
    if not raw:
        raise ValueError(
            "WALLET_PRIVATE_KEY belum di-set di Railway Variables!\n"
            "Isi dengan private key wallet Solana (format base58 atau JSON array)."
        )
    if raw.startswith("["):
        try:
            return Keypair.from_bytes(bytes(json.loads(raw)))
        except Exception as e:
            raise ValueError(f"WALLET_PRIVATE_KEY JSON array tidak valid: {e}")
    try:
        return Keypair.from_base58_string(raw)
    except Exception as e:
        raise ValueError(f"WALLET_PRIVATE_KEY base58 tidak valid: {e}")


# ── Step 1: Upload gambar + metadata ke IPFS (gratis, tanpa API key) ─────────

async def upload_metadata_to_ipfs(
    name: str,
    symbol: str,
    description: str,
    twitter: str,
    telegram: str,
    website: str,
    image_bytes: bytes,
    image_name: str = "logo.png",
    timeout: int = 90,
) -> str:
    """
    1. Upload gambar → dapat image URI
    2. Upload JSON metadata → dapat metadata URI
    Return: metadata URI (string)
    """
    mime = "image/png"
    if image_name.lower().endswith((".jpg", ".jpeg")):
        mime = "image/jpeg"
    elif image_name.lower().endswith(".gif"):
        mime = "image/gif"

    async with httpx.AsyncClient(timeout=timeout) as client:
        # --- Upload gambar ---
        logger.info("Uploading gambar ke IPFS...")
        img_resp = await client.post(
            IPFS_IMG_URL,
            files={"image": (image_name, image_bytes, mime)},
        )
        img_resp.raise_for_status()
        image_uri = img_resp.text.strip()
        logger.info(f"Image URI: {image_uri}")

        # --- Upload metadata JSON ---
        # Hanya field wajib, tambahkan opsional jika tidak kosong
        metadata: dict = {
            "name":      name,
            "symbol":    symbol,
            "description": description,
            "image":     image_uri,
            "createdOn": "https://bonk.fun",
        }
        if website:
            metadata["website"] = website
        if twitter:
            metadata["twitter"] = twitter
        if telegram:
            metadata["telegram"] = telegram

        logger.info("Uploading metadata JSON ke IPFS...")
        meta_resp = await client.post(
            IPFS_META_URL,
            headers={"Content-Type": "application/json"},
            content=json.dumps(metadata).encode(),
        )
        if meta_resp.status_code != 200:
            raise RuntimeError(
                f"Metadata upload gagal ({meta_resp.status_code}): {meta_resp.text[:300]}"
            )
        metadata_uri = meta_resp.text.strip()
        logger.info(f"Metadata URI: {metadata_uri}")

    return metadata_uri


# ── Step 2: Buat, sign, dan kirim transaksi token ────────────────────────────

async def create_token_transaction(
    name: str,
    symbol: str,
    metadata_uri: str,
    buy_sol: float = 0.0,
    slippage: int = 15,
    priority_fee: float = 0.00005,
    timeout: int = 60,
) -> dict:
    """
    POST ke pumpportal /api/trade-local → dapat serialized VersionedTransaction (bytes)
    Sign dengan [mint_keypair, signer_keypair]
    Kirim ke Solana via RPC
    Return: {"success": bool, "mint": str, "signature": str} atau {"success": False, "error": str}
    """
    try:
        signer_kp = _load_keypair()
        mint_kp   = Keypair()   # mint address baru, random setiap pembuatan

        # pumpportal menolak amount=0; pakai minimum 0.0001 jika user pilih tidak beli
        actual_amount = buy_sol if buy_sol > 0 else 0.0001

        payload = {
            "publicKey":        str(signer_kp.pubkey()),
            "action":           "create",
            "tokenMetadata": {
                "name":   name,
                "symbol": symbol,
                "uri":    metadata_uri,
            },
            "mint":             str(mint_kp.pubkey()),
            "denominatedInSol": "true",
            "amount":           actual_amount,
            "slippage":         slippage,
            "priorityFee":      priority_fee,
            "pool":             "pump",
        }

        # /api/trade-local mengharapkan LIST (array), bukan single object
        logger.info(f"Payload pumpportal: {[payload]}")

        async with httpx.AsyncClient(timeout=timeout) as client:
            logger.info("Meminta transaksi dari pumpportal /api/trade-local ...")
            resp = await client.post(
                PUMPPORTAL_LOCAL,
                json=[payload],   # <-- array!
                headers={"Content-Type": "application/json"},
            )

        logger.info(f"pumpportal status={resp.status_code} body={resp.text[:500]}")

        if resp.status_code != 200:
            return {
                "success": False,
                "error": f"pumpportal {resp.status_code}: {resp.text[:500]}",
            }

        # Response: JSON array of base58-encoded serialized transactions
        try:
            tx_list = resp.json()
            tx_b58  = tx_list[0]
        except Exception:
            # fallback: raw bytes (format lama)
            tx_list = None
            tx_b58  = None

        import base58 as _b58
        if tx_b58:
            tx_bytes = _b58.b58decode(tx_b58)
        else:
            tx_bytes = resp.content

        tx        = VersionedTransaction.from_bytes(tx_bytes)
        signed_tx = VersionedTransaction(tx.message, [mint_kp, signer_kp])

        # Kirim ke Solana RPC
        rpc_url = os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
        tx_b64  = base64.b64encode(bytes(signed_tx)).decode()

        async with httpx.AsyncClient(timeout=timeout) as client:
            rpc_resp = await client.post(
                rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "sendTransaction",
                    "params": [tx_b64, {"encoding": "base64", "skipPreflight": True}],
                },
            )
            rpc_data = rpc_resp.json()

        if "error" in rpc_data:
            return {"success": False, "error": str(rpc_data["error"])}

        signature = rpc_data.get("result", "")
        mint_addr = str(mint_kp.pubkey())
        logger.info(f"✅ Token dibuat! Mint={mint_addr} Sig={signature}")

        return {"success": True, "mint": mint_addr, "signature": signature}

    except httpx.HTTPStatusError as e:
        logger.exception("HTTP error")
        return {"success": False, "error": f"HTTP {e.response.status_code}: {e.response.text[:300]}"}
    except Exception as e:
        logger.exception("Error tidak terduga")
        return {"success": False, "error": str(e)}
