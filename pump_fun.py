"""
pump_fun.py — Integrasi dengan pump.fun / pumpportal.fun API

Flow:
  1. upload_metadata_to_ipfs() — upload gambar ke Pinata IPFS, lalu upload metadata JSON
  2. create_token_transaction() — POST ke pumpportal /api/trade-local, sign dg 2 keypair, kirim via RPC

Catatan penting (April 2025):
  - pump.fun/api/ipfs sudah MATI → harus pakai Pinata atau IPFS lain
  - Endpoint create BUKAN /api/create → gunakan /api/trade-local
  - Transaksi harus di-sign oleh DAUA keypair: mint keypair + signer keypair
"""

import os
import json
import base64
import logging
from typing import Optional

import httpx
from solders.keypair import Keypair                   # type: ignore
from solders.transaction import VersionedTransaction   # type: ignore

logger = logging.getLogger(__name__)

# Endpoint yang benar (per dokumentasi pumpportal April 2025)
PINATA_UPLOAD_URL  = "https://uploads.pinata.cloud/v3/files"
PINATA_GATEWAY     = "https://ipfs.io/ipfs"
PUMPPORTAL_LOCAL   = "https://pumpportal.fun/api/trade-local"


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


def _pinata_jwt() -> str:
    """Ambil Pinata JWT dari environment."""
    jwt = os.environ.get("PINATA_JWT", "").strip()
    if not jwt:
        raise ValueError(
            "PINATA_JWT belum di-set di Railway Variables!\n"
            "Daftar gratis di https://pinata.cloud → API Keys → buat JWT."
        )
    return jwt


# ── Step 1: Upload gambar + metadata ke Pinata IPFS ──────────────────────────

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
    1. Upload gambar ke Pinata → dapat CID gambar
    2. Upload JSON metadata ke Pinata → dapat CID metadata
    Return: metadata URI  (https://ipfs.io/ipfs/<cid>)
    """
    jwt = _pinata_jwt()
    headers = {"Authorization": f"Bearer {jwt}"}

    mime = "image/png"
    if image_name.lower().endswith(".jpg") or image_name.lower().endswith(".jpeg"):
        mime = "image/jpeg"
    elif image_name.lower().endswith(".gif"):
        mime = "image/gif"

    async with httpx.AsyncClient(timeout=timeout) as client:
        # --- Upload gambar ---
        logger.info("Uploading gambar ke Pinata...")
        img_resp = await client.post(
            PINATA_UPLOAD_URL,
            headers=headers,
            files={
                "network": (None, "public"),
                "file":    (image_name, image_bytes, mime),
            },
        )
        img_resp.raise_for_status()
        img_cid = img_resp.json()["data"]["cid"]
        image_url = f"{PINATA_GATEWAY}/{img_cid}"
        logger.info(f"Gambar CID: {img_cid}")

        # --- Upload metadata JSON ---
        metadata = {
            "name":        name,
            "symbol":      symbol,
            "description": description,
            "image":       image_url,
            "twitter":     twitter,
            "telegram":    telegram,
            "website":     website,
            "createdOn":   "https://pump.fun",
        }
        meta_bytes = json.dumps(metadata).encode()
        meta_file  = ("metadata.json", meta_bytes, "application/json")

        logger.info("Uploading metadata JSON ke Pinata...")
        meta_resp = await client.post(
            PINATA_UPLOAD_URL,
            headers=headers,
            files={
                "network": (None, "public"),
                "file":    meta_file,
            },
        )
        meta_resp.raise_for_status()
        meta_cid = meta_resp.json()["data"]["cid"]
        metadata_uri = f"{PINATA_GATEWAY}/{meta_cid}"
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
    POST ke pumpportal /api/trade-local → dapat serialized VersionedTransaction
    Sign dengan [mint_keypair, signer_keypair]
    Kirim ke Solana via RPC
    Return: {"success": bool, "mint": str, "signature": str} atau {"success": False, "error": str}
    """
    try:
        signer_kp = _load_keypair()
        mint_kp   = Keypair()          # mint address baru, random setiap pembuatan

        payload = {
            "publicKey":        str(signer_kp.pubkey()),
            "action":           "create",
            "tokenMetadata": {
                "name":   name,
                "symbol": symbol,
                "uri":    metadata_uri,
            },
            "mint":             str(mint_kp.pubkey()),  # public key, bukan secret!
            "denominatedInSol": "true",
            "amount":           buy_sol,
            "slippage":         slippage,
            "priorityFee":      priority_fee,
            "pool":             "pump",
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            logger.info("Meminta transaksi dari pumpportal /api/trade-local ...")
            resp = await client.post(
                PUMPPORTAL_LOCAL,
                json=payload,
                headers={"Content-Type": "application/json"},
            )

        if resp.status_code != 200:
            return {
                "success": False,
                "error": f"pumpportal HTTP {resp.status_code}: {resp.text[:300]}",
            }

        # Response: raw bytes serialized VersionedTransaction
        tx_bytes = resp.content
        tx       = VersionedTransaction.from_bytes(tx_bytes)

        # Sign dengan KEDUA keypair: mint_kp + signer_kp
        signed_tx = VersionedTransaction(tx.message, [mint_kp, signer_kp])

        # Kirim ke Solana RPC
        rpc_url   = os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
        tx_b64    = base64.b64encode(bytes(signed_tx)).decode()

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
