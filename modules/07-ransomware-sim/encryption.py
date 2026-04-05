#!/usr/bin/env python3
"""
Encryption utilities for ransomware simulation.
Provides AES-256 encryption and decryption for safe mode testing.
"""

import logging
import binascii
from pathlib import Path
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
from Crypto.Util.Padding import pad, unpad

logger = logging.getLogger(__name__)


def hex_key_to_bytes(hex_key: str) -> bytes:
    """
    Convert hex string key to bytes. Must be 32 chars for 256-bit AES.
    
    Args:
        hex_key: 32 hexadecimal characters representing the key
    
    Returns:
        32 bytes of key data
    
    Raises:
        ValueError: If key is not exactly 32 hex characters or invalid hex
    """
    if len(hex_key) != 32:
        raise ValueError(f"Key must be 32 hex characters (16 bytes), got {len(hex_key)}")
    try:
        return binascii.unhexlify(hex_key)
    except binascii.Error as e:
        raise ValueError(f"Invalid hex key format: {e}")


def encrypt_file_aes(file_path: Path, key_bytes: bytes) -> bool:
    """
    Encrypt file with AES-256-CBC.
    
    Format: [16-byte IV][encrypted data]
    The IV is randomly generated and stored with the ciphertext for easy decryption.
    
    Args:
        file_path: Path to file to encrypt
        key_bytes: 32-byte AES-256 key
    
    Returns:
        True if successful, False otherwise
    """
    try:
        # Read original file
        with open(file_path, 'rb') as f:
            plaintext = f.read()
        
        # Generate random IV (16 bytes)
        iv = get_random_bytes(16)
        
        # Create cipher
        cipher = AES.new(key_bytes, AES.MODE_CBC, iv)
        
        # Pad and encrypt
        padded_plaintext = pad(plaintext, AES.block_size)
        ciphertext = cipher.encrypt(padded_plaintext)
        
        # Write encrypted data: IV + ciphertext
        with open(file_path, 'wb') as f:
            f.write(iv + ciphertext)
        
        logger.info(f"Encrypted file: {file_path.name} ({len(plaintext)} → {len(iv) + len(ciphertext)} bytes)")
        return True
    
    except Exception as e:
        logger.error(f"Failed to encrypt {file_path}: {e}")
        return False


def decrypt_file_aes(file_path: Path, key_bytes: bytes) -> bool:
    """
    Decrypt file that was encrypted with encrypt_file_aes.
    
    Args:
        file_path: Path to encrypted file
        key_bytes: 32-byte AES-256 key
    
    Returns:
        True if successful, False otherwise
    """
    try:
        # Read encrypted file
        with open(file_path, 'rb') as f:
            encrypted_data = f.read()
        
        # Extract IV (first 16 bytes)
        iv = encrypted_data[:16]
        ciphertext = encrypted_data[16:]
        
        # Create cipher
        cipher = AES.new(key_bytes, AES.MODE_CBC, iv)
        
        # Decrypt and unpad
        padded_plaintext = cipher.decrypt(ciphertext)
        plaintext = unpad(padded_plaintext, AES.block_size)
        
        # Write decrypted data
        with open(file_path, 'wb') as f:
            f.write(plaintext)
        
        logger.info(f"Decrypted file: {file_path.name} ({len(encrypted_data)} → {len(plaintext)} bytes)")
        return True
    
    except Exception as e:
        logger.error(f"Failed to decrypt {file_path}: {e}")
        return False


def decrypt_files_aes(encrypted_dir: str, static_key_hex: str) -> int:
    """
    Decrypt files encrypted in safe mode.
    
    Usage: decrypt_files_aes('./encrypted_copies', '0123456789ABCDEF0123456789ABCDEF')
    
    Args:
        encrypted_dir: Directory containing encrypted files
        static_key_hex: 32-character hex string of encryption key
    
    Returns:
        Number of files successfully decrypted
    """
    try:
        key_bytes = hex_key_to_bytes(static_key_hex)
    except ValueError as e:
        logger.error(f"Invalid key: {e}")
        return 0
    
    encrypted_path = Path(encrypted_dir)
    if not encrypted_path.exists():
        logger.error(f"Directory not found: {encrypted_path}")
        return 0
    
    decrypted_count = 0
    
    # Decrypt all files in directory
    for file_path in encrypted_path.glob("*"):
        if file_path.is_file():
            if decrypt_file_aes(file_path, key_bytes):
                decrypted_count += 1
    
    logger.info(f"Decryption complete: {decrypted_count} files decrypted")
    return decrypted_count
