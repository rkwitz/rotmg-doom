// Drunk: RotMG's BlurFilter (a box blur, 20 to 30 of its 600 pixels high, pulsing). RADIUS:
// half the blur box, as a share of the screen's height.
void main()
{
	vec2 size = vec2(textureSize(InputTexture, 0));
	vec2 stride = vec2(radius * size.y / size.x, radius) / 3.0;
	vec4 sum = vec4(0.0);
	for (int y = -3; y <= 3; y++)
	{
		for (int x = -3; x <= 3; x++)
		{
			sum += texture(InputTexture, TexCoord + vec2(float(x), float(y)) * stride);
		}
	}
	FragColor = vec4((sum / 49.0).rgb, 1.0);
}
