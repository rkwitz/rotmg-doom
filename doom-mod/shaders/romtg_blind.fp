// Blind: RotMG's BLIND_FILTER, every channel 0.05 x (r + g + b): almost black, no colour.
void main()
{
	vec4 c = texture(InputTexture, TexCoord);
	float v = 0.05 * (c.r + c.g + c.b);
	FragColor = vec4(v, v, v, 1.0);
}
