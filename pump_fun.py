"""
pump_fun.py — Integrasi dengan pump.fun / pumpportal.fun API

Flow:
  1. upload_metadata_to_ipfs() — upload gambar + metadata ke IPFS via pump.fun
  2. create_token_transaction() — buat & sign transaksi Solana via pumpportal.fun
"""

import os
import json
import base64
import logging
import asyncio
from io import BytesIO
from typing import Optional

import httpx
from solders.keypair import Keypair                   # type: ignore
from solders.transaction import VersionedTransaction   # type: ignore

logger = logging.getLogger(__name__)

PUMP_IPFS_URL    = "https://pump.fun/api/ipfs"
PUMPPORTAL_URL   = "https://pumpportal.fun/api/create"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_keypair() -> Keypair:
    """Muat Solana keypair dari environment variable."""
    raw = os.environ.get("WALLET_PRIVATE_KEY", "")
    if not raw:
        raise ValueError(
            "WALLET_PRIVATE_KEY belum di-set. "
            "Isi dengan private key wallet Solana kamu (base58 atau JSON array)."
        )

    raw = raw.strip()

    # Format JSON array: [12, 34, ...]
    if raw.startswith("["):
        try:
            secret = bytes(json.loads(raw))
            return Keypair.from_bytes(secret)
        except Exception as e:
            raise ValueError(f"WALLET_PRIVATE_KEY format JSON array tidak valid: {e}")

    # Format base58
    try:
        return Keypair.from_base58_string(raw)
    except Exception as e:
        raise ValueError(f"WALLET_PRIVATE_KEY format base58 tidak valid: {e}")


# ── Step 1: Upload ke IPFS ────────────────────────────────────────────────────

async def upload_metadata_to_ipfs(
    name: str,
    symbol: str,
    description: str,
    twitter: str,
    telegram: str,
    website: str,
    image_bytes: bytes,
    image_name: str = "logo.jpg",
    timeout: int = 60,
) -> str:
    """
    Upload gambar + metadata ke IPFS pump.fun.
    Return: metadata URI (string)
    """
    mime = "image/gif" if image_name.lower().endswith(".gif") else "image/jpeg"
    if image_name.lower().endswith(".png"):
        mime = "image/png"

    form_data = {
        "name":        (None, name),
        "symbol":      (None, symbol),
        "description": (None, description),
        "twitter":     (None, twitter),
        "telegram":    (None, telegram),
        "website":     (None, website),
        "showName":    (None, "true"),
        "file":        (image_name, image_bytes, mime),
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            PUMP_IPFS_URL,
            files=form_data,
        )
        response.raise_for_status()
        result = response.json()

    metadata_uri = result.get("metadataUri") or result.get("uri") or result.get("url")
    if not metadata_uri:
        raise RuntimeError(f"IPFS upload gagal, response: {result}")

    logger.info(f"IPFS upload sukses: {metadata_uri}")
    return metadata_uri


# ── Step 2: Buat Token di Solana ──────────────────────────────────────────────

async def create_token_transaction(
    metadata_uri: str,
    buy_sol: float = 0.0,
    slippage_bps: int = 2500,
    priority_fee: float = 0.0005,
    timeout: int = 60,
) -> dict:
    """
    Buat, sign, dan kirim transaksi pembuatan token ke Solana via pumpportal.fun.
    Return: dict dengan key 'success', 'mint', 'signature', atau 'error'.
    """
    try:
        keypair    = _load_keypair()
        mint_kp    = Keypair()  # Keypair baru untuk mint address token

        payload = {
            "publicKey":        str(keypair.pubkey()),
            "action":           "create",
            "tokenMetadata": {
                "name":   "token",   # akan di-override dari metadata_uri
                "symbol": "TOKEN",   # akan di-override dari metadata_uri
                "uri":    metadata_uri,
            },
            "mint":             str(mint_kp.pubkey()),
            "denominatedInSol": "true",
            "amount":           buy_sol,
            "slippage":         slippage_bps,
            "priorityFee":      priority_fee,
            "pool":             "pump",
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            # Minta transaksi dari pumpportal
            resp = await client.post(
                PUMPPORTAL_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()

            if resp.headers.get("content-type", "").startswith("application/json"):
                data = resp.json()
                # Kalau sudah langsung berhasil (beberapa endpoint mengembalikan ini)
                if data.get("signature"):
                    return {
                        "success":   True,
                        "mint":      str(mint_kp.pubkey()),
                        "signature": data["signature"],
                    }
                raise RuntimeError(f"Response tidak dikenali: {data}")

            # Pumpportal mengembalikan transaksi dalam binary untuk kita sign
            tx_bytes = resp.content

        # Sign & kirim ke Solana RPC
        rpc_url = os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")

        tx      = VersionedTransaction.from_bytes(tx_bytes)
        signed  = keypair.sign_message(bytes(tx.message))

        # Solana sendTransaction via JSON-RPC
        async with httpx.AsyncClient(timeout=timeout) as client:
            rpc_resp = await client.post(
                rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "sendTransaction",
                    "params": [
                        base64.b64encode(bytes(tx)).decode(),
                        {"encoding": "base64", "skipPreflight": True},
                    ],
                },
            )
            rpc_data = rpc_resp.json()

        if "error" in rpc_data:
            return {"success": False, "error": str(rpc_data["error"])}

        signature = rpc_data.get("result", "")
        logger.info(f"Token berhasil dibuat! Mint={mint_kp.pubkey()} Sig={signature}")

        return {
            "success":   True,
            "mint":      str(mint_kp.pubkey()),
            "signature": signature,
        }

    except httpx.HTTPStatusError as e:
        logger.exception("HTTP error saat create token")
        return {"success": False, "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
    except Exception as e:
        logger.exception("Error tak terduga saat create token")
        return {"success": False, "error": str(e)}
