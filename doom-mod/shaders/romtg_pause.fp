// Paused: grey, as RotMG shows a paused player's world.
void main()
{
	vec4 c = texture(InputTexture, TexCoord);
	float v = dot(c.rgb, vec3(0.3, 0.59, 0.11));
	FragColor = vec4(v, v, v, 1.0);
}
