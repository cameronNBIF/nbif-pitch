export default {
  async fetch(request, env) {
    const allowedOrigins = [
      "https://dogfish-wedge-yb33.squarespace.com",
      "https://koi-chameleon-7kz5.squarespace.com",
      "https://nbif.ca",
      "https://www.nbif.ca",
      "https://finb.ca",
      "https://www.finb.ca",
    ];

    const origin = request.headers.get("Origin");
    const isAllowed = allowedOrigins.includes(origin);
    const corsOrigin = isAllowed ? origin : allowedOrigins[0];

    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": corsOrigin,
          "Access-Control-Allow-Methods": "POST, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type",
          "Vary": "Origin",
        },
      });
    }

    if (request.method !== "POST") {
      return new Response("Method not allowed", { status: 405 });
    }

    if (!isAllowed) {
      return new Response("Origin not allowed", { status: 403 });
    }

    const azureUrl = "https://nbif-pitch-func-gmfkhcfccbatgmdr.canadacentral-01.azurewebsites.net/api/pitch-intake";

    try {
      const azureResponse = await fetch(azureUrl, {
        method: "POST",
        headers: {
          "Content-Type": request.headers.get("Content-Type"),
          "x-functions-key": env.AZURE_FUNCTION_KEY.trim()
        },
        body: request.body
      });

      const responseData = await azureResponse.text();

      return new Response(responseData, {
        status: azureResponse.status,
        headers: {
          "Access-Control-Allow-Origin": corsOrigin,
          "Content-Type": "application/json",
          "Vary": "Origin",
        }
      });

    } catch (error) {
      return new Response("Error processing request", { status: 500 });
    }
  }
};