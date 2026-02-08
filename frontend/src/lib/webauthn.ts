/**
 * WebAuthn browser helpers for passkey registration and authentication.
 */

function base64urlToBuffer(base64url: string): ArrayBuffer {
  // Add padding
  let padded = base64url.replace(/-/g, '+').replace(/_/g, '/');
  while (padded.length % 4 !== 0) {
    padded += '=';
  }
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
}

function bufferToBase64url(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (const b of bytes) {
    binary += String.fromCharCode(b);
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export async function startRegistration(options: Record<string, unknown>): Promise<Record<string, unknown>> {
  const publicKey = options as Record<string, unknown>;

  // Convert challenge from base64url to ArrayBuffer
  const createOptions: PublicKeyCredentialCreationOptions = {
    ...publicKey,
    challenge: base64urlToBuffer(publicKey.challenge as string),
    user: {
      ...(publicKey.user as Record<string, unknown>),
      id: base64urlToBuffer((publicKey.user as Record<string, string>).id),
    } as PublicKeyCredentialUserEntity,
    excludeCredentials: ((publicKey.excludeCredentials as Array<Record<string, unknown>>) || []).map(
      (cred) => ({
        ...cred,
        id: base64urlToBuffer(cred.id as string),
      })
    ) as PublicKeyCredentialDescriptor[],
  };

  const credential = (await navigator.credentials.create({
    publicKey: createOptions,
  })) as PublicKeyCredential;

  if (!credential) {
    throw new Error('Failed to create credential');
  }

  const response = credential.response as AuthenticatorAttestationResponse;

  return {
    id: credential.id,
    rawId: bufferToBase64url(credential.rawId),
    type: credential.type,
    response: {
      attestationObject: bufferToBase64url(response.attestationObject),
      clientDataJSON: bufferToBase64url(response.clientDataJSON),
      transports: response.getTransports?.() || [],
    },
  };
}

export async function startAuthentication(options: Record<string, unknown>): Promise<Record<string, unknown>> {
  const publicKey = options as Record<string, unknown>;

  const getOptions: PublicKeyCredentialRequestOptions = {
    ...publicKey,
    challenge: base64urlToBuffer(publicKey.challenge as string),
    allowCredentials: ((publicKey.allowCredentials as Array<Record<string, unknown>>) || []).map(
      (cred) => ({
        ...cred,
        id: base64urlToBuffer(cred.id as string),
      })
    ) as PublicKeyCredentialDescriptor[],
  };

  const credential = (await navigator.credentials.get({
    publicKey: getOptions,
  })) as PublicKeyCredential;

  if (!credential) {
    throw new Error('Failed to get credential');
  }

  const response = credential.response as AuthenticatorAssertionResponse;

  return {
    id: credential.id,
    rawId: bufferToBase64url(credential.rawId),
    type: credential.type,
    response: {
      authenticatorData: bufferToBase64url(response.authenticatorData),
      clientDataJSON: bufferToBase64url(response.clientDataJSON),
      signature: bufferToBase64url(response.signature),
      userHandle: response.userHandle ? bufferToBase64url(response.userHandle) : null,
    },
  };
}
